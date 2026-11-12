from __future__ import annotations

from datetime import date


class DailyCap:
    """Tope de llamadas pagas por día. Protege contra cobros por un bucle o un abuso."""

    def __init__(self, limit: int):
        self.limit = limit
        self._day = date.today()
        self.used = 0

    def take(self) -> bool:
        today = date.today()
        if today != self._day:
            self._day, self.used = today, 0
        if self.used >= self.limit:
            return False
        self.used += 1
        return True
