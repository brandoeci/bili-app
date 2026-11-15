from __future__ import annotations

import asyncio
import json
import sys
import time
from collections import deque
from contextlib import asynccontextmanager
from typing import Any

import cv2
import numpy as np
from fastapi import FastAPI, WebSocket

from app.api.routes_debug import router as debug_router
from app.api.routes_describe import router as describe_router
from app.api.routes_routing import router as routing_router
from app.api.routes_session import router as session_router
from app.api.routes_stream import router as stream_router
from app.audio.earcons import EarconGenerator
from app.audio.tts import Speaker
from app.config import settings
from app.core.alerts import AlertManager
from app.core.camera import CaptureThread, RemoteCamera
from app.core.decision import confianza_minima
from app.core.depth import DepthModel
from app.core.detector import YoloDetector
from app.core.events import EventBus
from app.core.fusion import FusionEngine
from app.core.metrics import MetricsTracker
from app.core.pipeline import PerceptionPipeline
from app.scene.gemini_client import GeminiScene
from app.scene.narrator import NarrationGate, scene_signature
from app.scene.scheduler import SceneBusy, SceneScheduler
from app.scene.vlm_worker import VLMWorker
from app.schemas import ConfigUpdate, DescribeRequest


class VisionContext:
    def __init__(self, settings_obj: Any):
        self.settings = settings_obj
        if self.settings.camera_source == 'remote':
            self.camera = RemoteCamera()
        else:
            self.camera = CaptureThread(
                index=self.settings.camera_index,
                width=self.settings.camera_width,
                height=self.settings.camera_height,
                fps=self.settings.camera_fps,
            )
        self.detector = YoloDetector(
            model_path=str(self.settings.base_dir / self.settings.detector_model),
            conf=self.settings.detector_conf,
            iou=self.settings.detector_iou,
            classes=self.settings.detector_classes,
            device=self.settings.detector_device,
            tracker=self.settings.detector_tracker,
        )
        hazard_path = self.settings.base_dir / self.settings.hazard_model
        abstencion = self.settings.decision_abstencion
        tabla = self.settings.tabla_decision()
        self.hazard_detector = YoloDetector(
            model_path=str(hazard_path),
            # Con abstención, el detector deja pasar la banda intermedia y el motor de decisión decide qué decir con ella.
            conf=min(self.settings.hazard_conf, confianza_minima(tabla)) if abstencion else self.settings.hazard_conf,
            iou=self.settings.detector_iou,
            device=self.settings.detector_device,
            id_offset=100_000,
            class_conf={} if abstencion else self.settings.hazard_class_conf,
            tracker=self.settings.detector_tracker,
        ) if hazard_path.exists() else None
        self.depth = DepthModel(enabled=self.settings.depth_enabled, model_id=self.settings.depth_model, input_px=self.settings.depth_input_px)
        self._calibration_file = self.settings.base_dir / 'data' / 'calibration.json'
        self.fusion = FusionEngine(focal_ratio=self._load_focal_ratio(), proximity=self.settings.proximity_config(),
                                   decision=tabla, decidir_conducta=abstencion)
        self.alerts = AlertManager(
            critical_distance_m=self.settings.alerts_critical_distance_m,
            release_distance_m=self.settings.alerts_release_distance_m,
            cooldown_s=self.settings.alerts_cooldown_s,
            min_frames=self.settings.alerts_min_frames,
            max_speech_rate_s=self.settings.alerts_max_speech_rate_s,
            reminder_s=self.settings.alerts_reminder_s,
        )
        self.metrics = MetricsTracker()
        self.speaker = Speaker(voice=self.settings.audio_voice, rate=self.settings.audio_rate_wpm)
        self.earcons = EarconGenerator()
        self.gemini = GeminiScene(api_key=self.settings.gemini_api_key, model=self.settings.gemini_model, timeout=self.settings.gemini_timeout_s) if self.settings.gemini_api_key else None
        self.vlm = VLMWorker(self.settings.scene_vlm_model) if self.settings.scene_vlm_enabled else None
        self.scheduler = SceneScheduler(
            gemini=self.gemini,
            vlm=self.vlm,
            heuristic_interval_s=self.settings.scene_heuristic_interval_s,
            local_timeout_s=self.settings.scene_local_timeout_s,
            vlm_max_side_px=self.settings.scene_vlm_max_side_px,
            gemini_max_side_px=self.settings.scene_gemini_max_side_px,
            cache_ttl_s=self.settings.scene_cache_ttl_s,
        )
        self.bus = EventBus()
        self.pipeline = PerceptionPipeline(
            self.camera, self.detector, self.depth, self.fusion, self.alerts, self.metrics,
            bus=self.bus, depth_every_n=self.settings.depth_every_n_frames,
            hazard_detector=self.hazard_detector,
        )
        self.bus.subscribe('alert', self._on_alert)
        self.bus.subscribe('frame', self._on_frame)
        self.bus.subscribe('status', self._on_status)
        self.history: deque[dict[str, str]] = deque(maxlen=5)
        self._client_recent: dict[str, float] = {}
        self.quiet = self.settings.audio_verbosity == 'quiet'
        self.gate = NarrationGate(
            min_gap_s=self.settings.scene_min_gap_s,
            max_silence_s=self.settings.scene_max_silence_s,
        )
        self._last_frame_broadcast = 0.0
        self._outage_announced = False
        self.websockets: list[WebSocket] = []
        self._event_loop: asyncio.AbstractEventLoop | None = None
        self._scene_task: asyncio.Task | None = None
        self._last_scene_text = 'Sistema listo.'
        self._last_spoken_text: str | None = None
        self._last_alert_id: str | None = None

    def start(self) -> None:
        self.depth.start()
        if self.vlm is not None:
            self.vlm.start()
        if self.camera is not None and self.camera.is_open():
            self.pipeline.start()
        else:
            self.pipeline.start()

    def set_event_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._event_loop = loop

    def stop(self) -> None:
        if self._scene_task is not None:
            self._scene_task.cancel()
            self._scene_task = None
        self.pipeline.stop()
        if self.camera is not None:
            self.camera.stop()
        if self.vlm is not None:
            self.vlm.stop()
        self.speaker.shutdown()

    def start_scene_monitor(self) -> None:
        if self._event_loop is None or self._scene_task is not None and not self._scene_task.done():
            return
        self._scene_task = self._event_loop.create_task(self._scene_monitor())

    async def _scene_monitor(self) -> None:
        """Descripción automática: sólo pide al modelo cuando la escena cambió
        y sólo habla si el resultado aporta algo nuevo."""
        loop = asyncio.get_running_loop()
        while True:
            try:
                await asyncio.sleep(self.settings.scene_poll_s)
                detections = [d.model_dump() for d in self.pipeline.last_detections]
                signature = scene_signature(detections)
                now = loop.time()
                if not self.gate.should_request(signature, now):
                    continue
                self.gate.record_request(signature, now)
                result = await self.describe_scene(
                    DescribeRequest(mode=self.settings.scene_mode, task='scene', speak=False),
                    previous=self._last_spoken_text,
                    background=True,
                )
                self._handle_monitor_result(result, loop.time())
            except asyncio.CancelledError:
                raise
            except SceneBusy:
                continue
            except Exception as exc:
                self._broadcast_json({'type': 'description_error', 'error': f'{type(exc).__name__}: {exc}'})

    def _handle_monitor_result(self, result: dict[str, Any], now: float) -> None:
        text = str(result['text']).strip()
        if result.get('unchanged'):
            return
        if result.get('degraded'):
            # Las alertas reflejo ya cubren lo medido; sólo se avisa una vez de la caída.
            if not self._outage_announced:
                self._outage_announced = True
                self._say('La descripción detallada de la escena no está disponible por ahora.', priority='P2')
            return
        self._outage_announced = False
        if self.gate.is_repeat(text, now):
            return
        self.gate.record_announcement(text, now)
        self._last_spoken_text = text
        self._say(text, priority='P2')
        self._broadcast_json({'type': 'description', 'data': result})

    def _say(self, text: str, priority: str = 'P3', force: bool = False, system: bool = False) -> bool:
        """Único punto de salida de voz: aplica el modo silencioso y guarda historial."""
        if self.quiet and priority != 'P0':
            return False
        spoken = self._emit_speech(text, priority, force=force, interruptible=not system)
        if spoken:
            self.history.append({'text': text, 'priority': priority})
        return spoken

    def _emit_speech(self, text: str, priority: str, force: bool = False, interruptible: bool = True) -> bool:
        """Entrega la frase al celular (evento 'speak') y/o al motor de voz del servidor."""
        mode = self.settings.audio_output
        spoken = False
        if mode in {'client', 'both'} and self.websockets:
            text = (text or '').strip()
            key = ' '.join(text.casefold().split())
            now = time.monotonic()
            if text and (force or now - self._client_recent.get(key, -1e9) >= 6.0):
                self._client_recent = {k: t for k, t in self._client_recent.items() if now - t < 6.0}
                self._client_recent[key] = now
                self._broadcast_json({'type': 'speak', 'text': text, 'priority': priority, 'interruptible': interruptible})
                spoken = True
        if mode in {'server', 'both'}:
            spoken = self.speaker.say(text, priority=priority, force=force, interruptible=interruptible) or spoken
        return spoken

    def repeat_last(self, n: int = 1) -> str | None:
        items = list(self.history)
        if not items or n > len(items):
            return None
        item = items[-n]
        self._emit_speech(item['text'], 'P1', force=True)
        return item['text']

    def _on_status(self, status: str) -> None:
        if status == 'blocked':
            self._say('No veo bien: la cámara está tapada o hay muy poca luz. Use su bastón.', priority='P0', force=True)
        elif status == 'ok':
            self._say('La cámara volvió a ver con normalidad.', priority='P1', force=True)

    async def announce_when_ready(self, timeout_s: float = 150.0) -> None:
        """Dice por voz el estado del sistema: quien no ve la pantalla necesita saber cuándo puede confiar en él."""
        self._say('Iniciando el sistema.', priority='P1', force=True, system=True)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_s
        while loop.time() < deadline:
            await asyncio.sleep(1.0)
            health = self.health()
            models = health['models_loaded']
            loading = models['vlm_local_loading'] or self.depth.loading
            if not loading:
                break
        health = self.health()
        models = health['models_loaded']
        problems = []
        if not health['camera_open']:
            problems.append('la cámara no está disponible')
        if not models['detector']:
            problems.append('el detector de objetos no cargó')
        if self.depth.requested and not self.depth.enabled:
            problems.append('no hay medición de profundidad; no detectaré paredes ni escalones')
        if self.vlm is not None and not models['vlm_local'] and not models['gemini']:
            problems.append('la descripción de escena no está disponible')
        if problems:
            self._say('Sistema iniciado con limitaciones: ' + '; '.join(problems) + '.', priority='P0', force=True, system=True)
        else:
            self._say('Sistema listo.', priority='P1', force=True, system=True)

    def _on_alert(self, alert: Any) -> None:
        self._last_scene_text = alert.text
        self._broadcast_json({'type': 'alert', 'data': alert.model_dump()})
        if alert.priority in {'P0', 'P1'}:
            self._last_alert_id = alert.id
            self._say(alert.text, priority=alert.priority)
            self.earcons.trigger(direction='center', priority=alert.priority, distance_m=2.0)

    def _on_frame(self, event: Any) -> None:
        # El WebSocket recibe ~8 Hz; a 30 Hz saturaría al navegador sin aportar nada.
        now = time.monotonic()
        if now - self._last_frame_broadcast < 0.12:
            return
        self._last_frame_broadcast = now
        self._broadcast_json({'type': 'frame', 'data': event.model_dump()})

    def _broadcast_json(self, payload: dict[str, Any]) -> None:
        loop = self._event_loop
        if loop is None or not loop.is_running():
            return
        for ws in list(self.websockets):
            future = asyncio.run_coroutine_threadsafe(ws.send_json(payload), loop)
            future.add_done_callback(lambda f, ws=ws: f.exception() and self.unregister_ws(ws))

    def latest_frame(self) -> np.ndarray | None:
        frame = self.pipeline.last_frame
        if frame is None:
            frame, _ = self.camera.latest()
        if frame is None:
            return np.zeros((480, 640, 3), dtype=np.uint8)
        return frame

    def latest_raw_frame(self) -> np.ndarray | None:
        frame = self.pipeline.last_raw_frame
        if frame is None:
            frame, _ = self.camera.latest()
        return frame

    def _load_focal_ratio(self) -> float:
        try:
            return float(json.loads(self._calibration_file.read_text())['focal_ratio'])
        except (OSError, ValueError, KeyError):
            return self.settings.camera_focal_ratio

    def calibrate_distance(self, known_distance_m: float) -> dict[str, Any]:
        """Calibra la focal con la persona más grande visible a una distancia conocida."""
        people = [d for d in self.pipeline.last_detections if d.label == 'person']
        if not people:
            raise RuntimeError('No hay ninguna persona visible para calibrar')
        person = max(people, key=lambda d: d.bbox[3] - d.bbox[1])
        ratio = self.fusion.calibrate('person', person.bbox, self.settings.process_size, known_distance_m)
        self._calibration_file.parent.mkdir(exist_ok=True)
        self._calibration_file.write_text(json.dumps({'focal_ratio': ratio}))
        return {'focal_ratio': round(ratio, 4), 'known_distance_m': known_distance_m}

    def detect_image(self, image: np.ndarray):
        resized = cv2.resize(image, (self.settings.process_size, max(1, int((self.settings.process_size / max(1, image.shape[1])) * image.shape[0]))))
        detections = self.detector.track(resized)
        fused = self.fusion.update(detections, self.depth.infer(resized), resized.shape)
        return fused

    async def describe_scene(self, payload: DescribeRequest, previous: str | None = None, background: bool = False):
        detections = [d.model_dump() for d in self.pipeline.last_detections]
        frame = self.latest_raw_frame()
        if frame is None:
            frame = self.latest_frame()
        ok, encoded = await asyncio.to_thread(cv2.imencode, '.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        if not ok:
            raise RuntimeError('No se pudo codificar el frame actual para describir la escena')
        result = await self.scheduler.describe_scene(
            encoded.tobytes(),
            detections,
            mode=payload.mode,
            task=payload.task,
            question=payload.question,
            speak=payload.speak,
            previous=previous,
            background=background,
            navigation=self.pipeline.navigation,
        )
        if not background and not result.get('degraded'):
            self._last_scene_text = str(result['text'])
            if payload.task == 'scene':
                self._last_spoken_text = self._last_scene_text
            self._broadcast_json({'type': 'description', 'data': result})
        if payload.speak:
            self._say(str(result['text']), priority='P2')
        return result

    def current_config(self) -> dict[str, Any]:
        return {
            'scene_mode': self.settings.scene_mode,
            'camera_index': self.settings.camera_index,
            'detector_conf': self.settings.detector_conf,
            'audio_voice': self.settings.audio_voice,
            'audio_rate_wpm': self.settings.audio_rate_wpm,
            'audio_verbosity': self.settings.audio_verbosity,
            'gemini_configured': bool(self.settings.gemini_api_key),
            'gemini_model': self.settings.gemini_model,
            'detector_model': self.settings.detector_model,
        }

    def update_config(self, payload: ConfigUpdate) -> dict[str, Any]:
        if payload.scene_mode is not None:
            self.settings.scene_mode = payload.scene_mode
        if payload.camera_index is not None:
            self.settings.camera_index = payload.camera_index
        if payload.detector_conf is not None:
            self.settings.detector_conf = payload.detector_conf
        if payload.audio_rate_wpm is not None:
            self.settings.audio_rate_wpm = payload.audio_rate_wpm
            self.speaker.rate = payload.audio_rate_wpm
        if payload.audio_verbosity is not None:
            self.settings.audio_verbosity = payload.audio_verbosity
            self.quiet = payload.audio_verbosity == 'quiet'
        if payload.audio_voice is not None:
            self.settings.audio_voice = payload.audio_voice
            self.speaker.voice = payload.audio_voice
        return self.current_config()

    def health(self) -> dict[str, Any]:
        vlm_status = self.vlm.status() if self.vlm else {
            'ready': False,
            'loading': False,
            'alive': False,
            'model': None,
            'error': 'deshabilitado',
        }
        return {
            'status': 'ok',
            'camera_open': self.camera.is_open() if self.camera is not None else False,
            'camera': self.camera.status() if self.camera is not None else None,
            'models_loaded': {
                'detector': self.detector.model is not None,
                'detector_error': self.detector.error,
                'hazards': bool(self.hazard_detector and self.hazard_detector.model is not None),
                'hazards_error': self.hazard_detector.error if self.hazard_detector else 'sin models/bili-hazards.pt',
                'depth': self.depth.enabled,
                'depth_status': self.depth.status(),
                'vlm_local': vlm_status['ready'],
                'vlm_local_loading': vlm_status['loading'],
                'vlm_local_alive': vlm_status['alive'],
                'vlm_local_model': vlm_status['model'],
                'vlm_local_error': vlm_status['error'],
                'gemini': bool(self.gemini and self.gemini.client),
                'gemini_model': self.settings.gemini_model,
                'gemini_last_error': self.gemini.last_error if self.gemini else 'no configurado',
                'gemini_last_success_at': self.gemini.last_success_at if self.gemini else None,
            },
            'fps': self.pipeline.fps,
            'last_scene': self._last_scene_text,
        }

    def depth_preview_jpeg(self) -> bytes | None:
        """Mapa de profundidad coloreado (cerca=rojo) para ajustar y depurar."""
        depth = self.pipeline.last_depth
        if depth is None:
            return None
        norm = np.clip((depth - 0.3) / 5.0, 0, 1)
        color = cv2.applyColorMap((255 * (1 - norm)).astype(np.uint8), cv2.COLORMAP_TURBO)
        ok, buf = cv2.imencode('.jpg', color)
        return buf.tobytes() if ok else None

    def metrics_snapshot(self) -> dict[str, Any]:
        return {
            'latency_ms': self.metrics.snapshot(),
            'ram_mb': self._ram_mb(),
            'fps': self.pipeline.fps,
            'last_scene': self._last_scene_text,
        }

    @staticmethod
    def _ram_mb() -> float:
        try:
            import resource  # solo existe en Unix
        except ImportError:
            try:
                import psutil
                return round(psutil.Process().memory_info().rss / (1024 * 1024), 1)
            except ImportError:
                return 0.0
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return round(peak / (1024 * 1024 if sys.platform == 'darwin' else 1024), 1)

    def register_ws(self, websocket: WebSocket) -> None:
        first = not self.websockets
        self.websockets.append(websocket)
        # El celular no estaba conectado cuando arrancó el sistema: se le dice el estado al llegar.
        if first and self.settings.audio_output in {'client', 'both'}:
            self._ready_task = asyncio.get_running_loop().create_task(self.announce_when_ready())

    def unregister_ws(self, websocket: WebSocket) -> None:
        if websocket in self.websockets:
            self.websockets.remove(websocket)


app_state = VisionContext(settings)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    app_state.set_event_loop(asyncio.get_running_loop())
    app_state.start()
    # Con voz en el celular el aviso se da al conectarse (register_ws); aquí solo si habla el servidor.
    ready_task = (
        asyncio.create_task(app_state.announce_when_ready())
        if app_state.settings.audio_output in {'server', 'both'}
        else None
    )
    yield
    if ready_task is not None:
        ready_task.cancel()
    app_state.stop()


app = FastAPI(title='Vision Asistiva', version='1.0.0', lifespan=lifespan)
app.include_router(debug_router)
app.include_router(session_router)
app.include_router(describe_router)
app.include_router(routing_router)
app.include_router(stream_router)
if settings.onnx_spike:
    from app.api.routes_spike import router as spike_router

    app.include_router(spike_router)
# Siempre activo: lo que llegue por un túnel de Cloudflare solo ve la página de prueba, con clave; sin la prueba activa, nada.
from app.api.routes_spike import SoloPruebaPorTunel  # noqa: E402

app.add_middleware(SoloPruebaPorTunel, clave=settings.onnx_spike_clave if settings.onnx_spike else '')


if __name__ == '__main__':
    import uvicorn

    uvicorn.run('app.main:app', host=settings.host, port=settings.port, workers=settings.workers)
