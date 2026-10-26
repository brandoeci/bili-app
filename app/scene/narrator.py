from __future__ import annotations

from collections import deque
from difflib import SequenceMatcher
from typing import Any

_BAND_EDGES = (1.2, 2.5, 4.5)


def scene_signature(detections: list[dict[str, Any]]) -> frozenset:
    """Firma gruesa de la escena: qué hay, de qué lado y en qué banda de distancia.

    Ignora ids de track y posiciones exactas (que cambian cada frame), de modo
    que sólo un cambio real de la escena dispara una nueva descripción."""
    items = set()
    for d in detections:
        dist = d.get('distance_m')
        if dist is None or d.get('priority') == 'P3':
            continue
        band = sum(dist >= edge for edge in _BAND_EDGES)
        items.add((d.get('label'), d.get('direction'), band))
    return frozenset(items)


class NarrationGate:
    """Decide cuándo pedir y cuándo decir una descripción automática.

    - Pide una descripción sólo si la escena cambió (con un mínimo de espera)
      o si pasó demasiado tiempo en silencio.
    - No dice una descripción igual o casi igual a una reciente."""

    def __init__(
        self,
        min_gap_s: float = 8.0,
        max_silence_s: float = 45.0,
        similarity: float = 0.8,
        memory_s: float = 120.0,
        history: int = 6,
    ):
        self.min_gap_s = min_gap_s
        self.max_silence_s = max_silence_s
        self.similarity = similarity
        self.memory_s = memory_s
        self._last_signature: frozenset | None = None
        self._last_request_at = -1e9
        self._announced: deque[tuple[float, str]] = deque(maxlen=history)

    def should_request(self, signature: frozenset, now: float) -> bool:
        elapsed = now - self._last_request_at
        if self._last_signature is None:
            return True
        if signature != self._last_signature and elapsed >= self.min_gap_s:
            return True
        return elapsed >= self.max_silence_s

    def record_request(self, signature: frozenset, now: float) -> None:
        self._last_signature = signature
        self._last_request_at = now

    @staticmethod
    def _norm(text: str) -> str:
        return ' '.join(text.casefold().replace('.', ' ').replace(',', ' ').split())

    def is_repeat(self, text: str, now: float) -> bool:
        new = self._norm(text)
        for ts, old in self._announced:
            if now - ts <= self.memory_s and SequenceMatcher(None, new, old).ratio() >= self.similarity:
                return True
        return False

    def record_announcement(self, text: str, now: float) -> None:
        self._announced.append((now, self._norm(text)))

    @property
    def last_text(self) -> str | None:
        return self._announced[-1][1] if self._announced else None
