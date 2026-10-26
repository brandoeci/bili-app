from __future__ import annotations

import cv2
import numpy as np


class FrameQuality:
    """Detecta cámara tapada / sin luz / desenfocada de forma sostenida.

    Devuelve 'blocked' o 'ok' sólo cuando el estado cambia (histéresis por
    número de frames), para anunciarlo una vez y no a cada frame."""

    def __init__(self, bad_frames: int = 20, good_frames: int = 10, min_brightness: float = 18.0, min_sharpness: float = 6.0):
        self.bad_frames, self.good_frames = bad_frames, good_frames
        self.min_brightness, self.min_sharpness = min_brightness, min_sharpness
        self._bad = self._good = 0
        self.blocked = False

    def check(self, frame_bgr: np.ndarray) -> str | None:
        gray = cv2.cvtColor(cv2.resize(frame_bgr, (64, 36), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
        bad = float(gray.mean()) < self.min_brightness or float(cv2.Laplacian(gray, cv2.CV_32F).var()) < self.min_sharpness
        if bad:
            self._bad, self._good = self._bad + 1, 0
            if not self.blocked and self._bad >= self.bad_frames:
                self.blocked = True
                return 'blocked'
        else:
            self._good, self._bad = self._good + 1, 0
            if self.blocked and self._good >= self.good_frames:
                self.blocked = False
                return 'ok'
        return None
