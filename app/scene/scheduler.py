from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from app.scene.gemini_client import GeminiScene
from app.scene.heuristic import describe_from_detections
from app.scene.postprocess import clean, is_no_change, reconcile_with_sensors
from app.scene.prompts import build_prompt
from app.scene.providers import GeminiProvider, LocalVLMProvider, SceneProvider, SceneRequest
from app.scene.vlm_worker import VLMUnavailable, VLMWorker

log = logging.getLogger(__name__)


class SceneBusy(RuntimeError):
    """Ya hay una descripción en curso; la petición de fondo no se encola."""


class SceneScheduler:
    """Cadena de proveedores (Strategy + Chain of Responsibility).

    local → gemini → heurística, o gemini primero para leer texto. Cada
    proveedor tiene circuit breaker y presupuesto de tiempo propio; la
    heurística siempre responde pero se marca ``degraded``."""

    def __init__(
        self,
        gemini: GeminiScene | None = None,
        vlm: VLMWorker | None = None,
        heuristic_interval_s: float = 60.0,  # conservado por compatibilidad de configuración
        local_timeout_s: float = 15.0,
        vlm_max_side_px: int = 512,
        gemini_max_side_px: int = 640,
        cache_ttl_s: float = 5.0,
    ):
        self.providers: dict[str, SceneProvider] = {}
        if vlm is not None:
            self.providers['vlm_local'] = LocalVLMProvider(vlm, vlm_max_side_px, local_timeout_s)
        if gemini is not None:
            self.providers['gemini'] = GeminiProvider(gemini, gemini_max_side_px)
        self.local_timeout_s = local_timeout_s
        self.gemini_timeout_s = (gemini.timeout if gemini is not None else 20.0) + 2.0
        self.cache_ttl_s = cache_ttl_s
        self.last_scene_at = 0.0
        self._busy = asyncio.Lock()
        self._cache: tuple[tuple, float, dict] | None = None

    # -- orden de la cadena según modo y tarea -------------------------------
    def _chain(self, mode: str, task: str) -> list[str]:
        if mode == 'local':
            order = ['vlm_local']
        elif mode == 'gemini':
            order = ['gemini']
        elif task == 'read_text':  # el OCR de un VLM pequeño local es débil
            order = ['gemini', 'vlm_local']
        else:
            order = ['vlm_local', 'gemini']
        return [name for name in order if name in self.providers]

    @staticmethod
    def _signature(detections: list[dict[str, Any]]) -> tuple:
        return tuple(sorted(
            (d.get('label'), d.get('direction'), round(float(d.get('distance_m') or 0) / 1.5))
            for d in detections if d.get('priority') != 'P3'
        ))

    async def describe_scene(
        self,
        jpeg: bytes,
        detections: list[dict[str, Any]],
        mode: str = 'auto',
        task: str = 'scene',
        question: str | None = None,
        speak: bool = True,
        previous: str | None = None,
        background: bool = False,
        navigation: dict | None = None,
    ) -> dict[str, Any]:
        started = time.monotonic()
        cache_key = (mode, task, question, self._signature(detections))
        if (
            task == 'scene' and previous is None and self._cache is not None
            and self._cache[0] == cache_key and time.monotonic() - self._cache[1] < self.cache_ttl_s
        ):
            return {**self._cache[2], 'cached': True, 'latency_ms': 0.0}

        if background and self._busy.locked():
            raise SceneBusy('Descripción en curso')

        async with self._busy:
            prompt = build_prompt(task, detections, question, previous if task == 'scene' else None, navigation)
            request = SceneRequest(jpeg=jpeg, prompt=prompt, task=task)
            trace: list[dict[str, Any]] = []
            text: str | None = None
            source = 'heuristic'

            for name in self._chain(mode, task):
                provider = self.providers[name]
                if not provider.available():
                    trace.append({'source': name, 'ok': False, 'error': 'circuito abierto'})
                    continue
                budget = self.local_timeout_s if name == 'vlm_local' else self.gemini_timeout_s
                t0 = time.monotonic()
                try:
                    raw = await asyncio.wait_for(provider.describe(request), timeout=budget + 1.0)
                    text = clean(raw)
                    if text is None:
                        raise RuntimeError('respuesta vacía')
                    provider.breaker.success()
                    source = name
                    trace.append({'source': name, 'ok': True, 'ms': round((time.monotonic() - t0) * 1000)})
                    break
                except Exception as exc:
                    # "ocupado/cargando" no es un fallo del modelo: no cuenta para el breaker.
                    if not isinstance(exc, VLMUnavailable):
                        provider.breaker.failure()
                    trace.append({
                        'source': name, 'ok': False, 'ms': round((time.monotonic() - t0) * 1000),
                        'error': f'{type(exc).__name__}: {exc}',
                    })
                    log.warning('Proveedor %s falló: %s', name, exc)
                    text = None

            unchanged = False
            degraded = False
            if text is None:
                text, source, degraded = describe_from_detections(detections), 'heuristic', True
            elif is_no_change(text):
                unchanged = True
            elif task == 'scene':
                text = reconcile_with_sensors(text, detections)

            self.last_scene_at = time.time()
            result = {
                'text': text,
                'source': source,
                'latency_ms': round((time.monotonic() - started) * 1000, 2),
                'degraded': degraded,
                'unchanged': unchanged,
                'trace': trace,
            }
            if task == 'scene' and not degraded and not unchanged and previous is None:
                self._cache = (cache_key, time.monotonic(), result)
            return result
