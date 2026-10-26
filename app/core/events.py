from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable
from typing import Any

log = logging.getLogger(__name__)


class EventBus:
    """Patrón Observer: el pipeline publica y los consumidores (WebSocket, voz,
    métricas) se suscriben sin que el pipeline los conozca."""

    def __init__(self) -> None:
        self._subs: dict[str, list[Callable[[Any], None]]] = defaultdict(list)

    def subscribe(self, topic: str, handler: Callable[[Any], None]) -> None:
        self._subs[topic].append(handler)

    def publish(self, topic: str, payload: Any) -> None:
        for handler in list(self._subs.get(topic, ())):
            try:
                handler(payload)
            except Exception:  # un suscriptor roto no debe detener la percepción
                log.exception('Suscriptor falló en %s', topic)
