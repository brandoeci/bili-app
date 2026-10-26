from __future__ import annotations

import time


class EarconGenerator:
    def __init__(self):
        self._last = 0.0

    def trigger(self, direction: str = 'center', priority: str = 'P1', distance_m: float | None = None) -> None:
        # El sistema no requiere un backend de audio real en esta fase;remos desde el código
        # para dejar el punto de extensión listo para un tono espacial en un futuro.
        _ = (direction, priority, distance_m)
        self._last = time.perf_counter()
