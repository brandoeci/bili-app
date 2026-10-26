from __future__ import annotations

import threading
import time

import cv2
import numpy as np


class RemoteCamera:
    """Fuente de frames empujados desde fuera (el celular, por /ws/frames).
    Mantiene la misma interfaz que CaptureThread: el pipeline no distingue de dónde viene la imagen."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._frame: np.ndarray | None = None
        self._ts = 0.0
        self.frames_received = 0

    def push_jpeg(self, data: bytes) -> bool:
        frame = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            return False
        with self._lock:
            self._frame = frame
            self._ts = time.perf_counter()
            self.frames_received += 1
        return True

    def latest(self) -> tuple[np.ndarray | None, float]:
        with self._lock:
            frame = self._frame.copy() if self._frame is not None else None
            ts = self._ts
        return frame, ts

    def read(self) -> tuple[np.ndarray | None, float]:
        return self.latest()

    def is_open(self) -> bool:
        """Abierta = está llegando imagen reciente del celular."""
        with self._lock:
            return self._ts > 0 and (time.perf_counter() - self._ts) < 3.0

    def status(self) -> dict[str, object]:
        with self._lock:
            age = (time.perf_counter() - self._ts) * 1000.0 if self._ts else None
            has_frame = self._frame is not None
        return {
            'open': self.is_open(),
            'has_frame': has_frame,
            'last_frame_age_ms': round(age, 1) if age is not None else None,
            'error': None if has_frame else 'Esperando imagen del celular',
            'source': 'remote',
        }

    def stop(self) -> None:
        pass


class CaptureThread:
    def __init__(self, index: int = 0, width: int = 1280, height: int = 720, fps: int = 30):
        self.index = index
        self.width = width
        self.height = height
        self.fps = fps
        self._run = True
        self._lock = threading.Lock()
        self._frame = None
        self._ts = 0.0
        self._opened = False
        self._error: str | None = None

        try:
            backend = cv2.CAP_AVFOUNDATION if hasattr(cv2, 'CAP_AVFOUNDATION') else cv2.CAP_ANY
            self.cap = cv2.VideoCapture(index, backend)
            if self.cap is None or not self.cap.isOpened():
                self.cap = None
                self._error = f'No se pudo abrir la cámara con índice {index}'
                return

            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            self.cap.set(cv2.CAP_PROP_FPS, fps)
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            self._opened = True
            self.thread = threading.Thread(target=self._loop, daemon=True)
            self.thread.start()
        except Exception as exc:
            self.cap = None
            self._opened = False
            self._error = f'{type(exc).__name__}: {exc}'

    def _loop(self) -> None:
        while self._run:
            if self.cap is None:
                time.sleep(0.01)
                continue
            ok, frame = self.cap.read()
            if not ok or frame is None:
                time.sleep(0.01)
                continue
            with self._lock:
                self._frame = frame.copy()
                self._ts = time.perf_counter()

    def latest(self) -> tuple[np.ndarray | None, float]:
        with self._lock:
            frame = self._frame.copy() if self._frame is not None else None
            ts = self._ts
        return frame, ts

    def read(self) -> tuple[np.ndarray | None, float]:
        return self.latest()

    def is_open(self) -> bool:
        return self._opened and self.cap is not None and self.cap.isOpened()

    def status(self) -> dict[str, object]:
        with self._lock:
            has_frame = self._frame is not None
            last_frame_age_ms = ((time.perf_counter() - self._ts) * 1000.0) if self._ts else None
        return {
            'open': self.is_open(),
            'has_frame': has_frame,
            'last_frame_age_ms': round(last_frame_age_ms, 1) if last_frame_age_ms is not None else None,
            'error': self._error,
        }

    def stop(self) -> None:
        self._run = False
        if self.cap is not None:
            self.cap.release()
