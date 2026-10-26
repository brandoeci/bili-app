from __future__ import annotations

import threading
import time
from collections import deque

import cv2

from app.core.alerts import AlertManager
from app.core.depth import DepthModel
from app.core.detector import YoloDetector
from app.core.events import EventBus
from app.core.fusion import FusionEngine
from app.core.metrics import MetricsTracker
from app.core.navigation import PathAnalysis, PathAnalyzer, hazard_priority
from app.core.overlay import draw_overlay
from app.core.quality import FrameQuality
from app.schemas import Alert, Detection, FrameEvent


class PerceptionPipeline:
    def __init__(self, camera, detector: YoloDetector, depth: DepthModel, fusion: FusionEngine, alerts: AlertManager, metrics: MetricsTracker, bus: EventBus | None = None, depth_every_n: int = 3, hazard_detector: YoloDetector | None = None):
        self.camera = camera
        self.detector = detector
        self.hazard_detector = hazard_detector  # huecos, bordillos, escaleras...: modelo propio, aparte del de COCO
        self.depth = depth
        self.fusion = fusion
        self.alerts = alerts
        self.metrics = metrics
        self.bus = bus or EventBus()
        self.depth_every_n = max(1, depth_every_n)
        self._fps = 0.0
        self.path = PathAnalyzer()
        self.quality = FrameQuality()
        self._last_depth = None
        self._last_nav: PathAnalysis | None = None
        self._hazard_ids: dict[tuple[str, str], int] = {}
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_frame = None
        self._last_raw_frame = None
        self._last_detections: list[Detection] = []
        self._last_alerts: deque[Alert] = deque(maxlen=50)
        self._lock = threading.Lock()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)

    def _loop(self) -> None:
        last_ts = 0.0
        depth_step = 0
        tick = time.perf_counter()
        while not self._stop_event.is_set():
            frame, ts = self.camera.latest()
            if frame is None or ts == last_ts:
                time.sleep(0.005)
                continue
            last_ts = ts
            depth_step += 1

            t0 = time.perf_counter()
            process_w = 640
            h, w = frame.shape[:2]
            process_h = max(1, int((process_w / max(1, w)) * h))
            small = cv2.resize(frame, (process_w, process_h), interpolation=cv2.INTER_LINEAR)

            if (change := self.quality.check(small)) is not None:
                self.bus.publish('status', change)
            t1 = time.perf_counter()
            dets = self.detector.track(small)
            if self.hazard_detector is not None and self.hazard_detector.model is not None:
                dets = dets + self.hazard_detector.track(small)
            t2 = time.perf_counter()
            if self.depth.enabled:
                if depth_step % self.depth_every_n == 0:
                    self._last_depth = self.depth.infer(small)
                    if self._last_depth is not None:
                        self._last_nav = self.path.analyze(self._last_depth)
            else:
                self._last_depth = self._last_nav = None
            depth_map = self._last_depth
            t3 = time.perf_counter()
            fused = self.fusion.update(dets, depth_map, small.shape)
            if self._last_nav is not None:
                fused = fused + self._hazard_detections(self._last_nav, small.shape)
            t4 = time.perf_counter()

            for alert in self.alerts.evaluate(fused):
                self._last_alerts.append(alert)
                self.bus.publish('alert', alert)

            overlay = draw_overlay(small, fused)
            self._last_raw_frame = frame
            self._last_frame = cv2.resize(overlay, (w, h), interpolation=cv2.INTER_NEAREST)
            self._last_detections = fused

            now = time.perf_counter()
            self._fps = 0.9 * self._fps + 0.1 / max(1e-6, now - tick) if self._fps else 1.0 / max(1e-6, now - tick)
            tick = now
            total = (now - t0) * 1000.0
            self.metrics.record('perception_total_ms', total)
            self.metrics.record('yolo_ms', (t2 - t1) * 1000.0)
            self.bus.publish('frame', FrameEvent(
                ts=time.time(),
                fps=round(self._fps, 1),
                latency_ms={
                    'capture': round((t1 - t0) * 1000.0, 2),
                    'yolo': round((t2 - t1) * 1000.0, 2),
                    'depth': round((t3 - t2) * 1000.0, 2),
                    'fuse': round((t4 - t3) * 1000.0, 2),
                    'total': round(total, 2),
                },
                detections=fused,
                navigation=self._last_nav.as_dict() if self._last_nav else None,
            ))

    def _hazard_detections(self, nav: PathAnalysis, shape: tuple[int, ...]) -> list[Detection]:
        """Convierte peligros del suelo/paredes en detecciones para reutilizar alertas y overlay."""
        h, w = shape[:2]
        out = []
        for hz in nav.hazards:
            key = (hz.kind, hz.direction)
            track_id = self._hazard_ids.setdefault(key, -(len(self._hazard_ids) + 1))
            x1, y1, x2, y2 = hz.bbox_norm
            out.append(Detection(
                track_id=track_id, label=hz.kind, conf=0.6,
                bbox=(int(x1 * w), int(y1 * h), int(x2 * w), int(y2 * h)),
                direction=hz.direction, clock={'left': 10, 'center': 12, 'right': 2}[hz.direction],
                distance_m=round(hz.distance_m, 2),
                priority=hazard_priority(hz.kind, hz.direction, hz.distance_m),
                note=hz.note,
            ))
        return out

    @property
    def navigation(self) -> dict | None:
        return self._last_nav.as_dict() if self._last_nav else None

    @property
    def last_depth(self):
        return self._last_depth

    @property
    def fps(self) -> float:
        return round(self._fps, 1)

    @property
    def last_frame(self):
        return self._last_frame

    @property
    def last_raw_frame(self):
        return self._last_raw_frame

    @property
    def last_detections(self):
        return self._last_detections
