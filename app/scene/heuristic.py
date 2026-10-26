from __future__ import annotations

from typing import Any

from app.core.alerts import AlertManager
from app.core.labels import label_es

_SIDE = {'left': 'a su izquierda', 'right': 'a su derecha', 'center': 'al frente'}
_RANK = {'P0': 0, 'P1': 1, 'P2': 2, 'P3': 3}


def describe_from_detections(detections: list[dict[str, Any]], limit: int = 3) -> str:
    """Último recurso cuando ningún modelo de escena responde.

    Sólo reporta lo que el detector midió y declara explícitamente que no hay
    descripción completa. Nunca afirma que el camino está libre."""
    items = [d for d in detections if d.get('distance_m') is not None and d.get('priority') != 'P3']
    items.sort(key=lambda d: (_RANK.get(d.get('priority', 'P3'), 3), d['distance_m']))
    if not items:
        return 'Descripción detallada no disponible. No detecto objetos cercanos, pero avance con precaución.'
    parts = [
        f"{label_es(str(d['label']))} {_SIDE.get(d.get('direction'), 'al frente')}, "
        f"{AlertManager.spoken_distance(float(d['distance_m']))}"
        for d in items[:limit]
    ]
    return 'Descripción detallada no disponible. Detecto: ' + '; '.join(parts) + '.'
