from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Protocol

import cv2
import numpy as np

from app.scene.gemini_client import GeminiScene
from app.scene.vlm_worker import VLMWorker


@dataclass(frozen=True)
class SceneRequest:
    jpeg: bytes
    prompt: str
    task: str


class SceneProvider(Protocol):
    """Strategy: cada fuente de descripción implementa la misma interfaz."""

    name: str

    def available(self) -> bool: ...

    async def describe(self, request: SceneRequest) -> str: ...


class CircuitBreaker:
    """Tras N fallos seguidos el proveedor se salta durante `cooldown_s`, para
    no pagar un timeout completo en cada petición mientras está caído."""

    def __init__(self, threshold: int = 3, cooldown_s: float = 30.0):
        self.threshold = threshold
        self.cooldown_s = cooldown_s
        self._failures = 0
        self._opened_at = 0.0

    @property
    def open(self) -> bool:
        if self._failures < self.threshold:
            return False
        if time.monotonic() - self._opened_at >= self.cooldown_s:
            self._failures = self.threshold - 1  # half-open: permite un intento
            return False
        return True

    def success(self) -> None:
        self._failures = 0

    def failure(self) -> None:
        self._failures += 1
        if self._failures >= self.threshold:
            self._opened_at = time.monotonic()


def shrink_jpeg(jpeg: bytes, max_side: int, quality: int = 80) -> bytes:
    """Reduce el lado mayor: menos tokens de imagen = inferencia más rápida."""
    if max_side <= 0:
        return jpeg
    image = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        return jpeg
    h, w = image.shape[:2]
    scale = max_side / max(h, w)
    if scale >= 1:
        return jpeg
    image = cv2.resize(image, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode('.jpg', image, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    return buf.tobytes() if ok else jpeg


class LocalVLMProvider:
    name = 'vlm_local'
    _TOKENS = {'scene': 90, 'ask': 140, 'read_text': 160}

    def __init__(self, worker: VLMWorker, max_side_px: int = 512, timeout_s: float = 15.0):
        self.worker = worker
        self.max_side_px = max_side_px
        self.timeout_s = timeout_s
        self.breaker = CircuitBreaker(threshold=3, cooldown_s=20.0)

    def available(self) -> bool:
        return not self.breaker.open

    async def describe(self, request: SceneRequest) -> str:
        image = await asyncio.to_thread(shrink_jpeg, request.jpeg, self.max_side_px)
        return await asyncio.to_thread(
            self.worker.describe, image, request.prompt, self.timeout_s, self._TOKENS.get(request.task, 90)
        )


class GeminiProvider:
    name = 'gemini'

    def __init__(self, client: GeminiScene, max_side_px: int = 640):
        self.client = client
        self.max_side_px = max_side_px
        self.breaker = CircuitBreaker(threshold=2, cooldown_s=45.0)

    def available(self) -> bool:
        return self.client.client is not None and not self.breaker.open

    async def describe(self, request: SceneRequest) -> str:
        image = await asyncio.to_thread(shrink_jpeg, request.jpeg, self.max_side_px)
        return await self.client.describe(image, request.prompt)
