from __future__ import annotations

from collections import defaultdict, deque


class MetricsTracker:
    def __init__(self):
        self._samples: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=500))

    def record(self, name: str, value_ms: float) -> None:
        self._samples[name].append(value_ms)

    def snapshot(self) -> dict[str, dict[str, float]]:
        out: dict[str, dict[str, float]] = {}
        for name, values in self._samples.items():
            if not values:
                continue
            ordered = sorted(values)
            p50 = ordered[max(0, int(len(ordered) * 0.5) - 1)]
            p95 = ordered[min(len(ordered) - 1, max(0, int(len(ordered) * 0.95) - 1))]
            out[name] = {'p50_ms': round(p50, 2), 'p95_ms': round(p95, 2), 'count': len(values)}
        return out
