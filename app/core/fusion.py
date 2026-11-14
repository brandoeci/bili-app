from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import numpy as np

from app.core.labels import GROUND, HAZARDS, MOVING, REAL_HEIGHT_M, REAL_WIDTH_M, VEHICLES
from app.core.proximity import ProximityConfig
from app.schemas import Detection

_CAMERA_HEIGHT_M = 1.3
_GROUND_FAR_M = 10.0
_DEFAULT_HEIGHT_M = 0.7
_CLIPPED_BASE_FACTOR = 0.5
_DEFAULT_FOCAL_RATIO = 0.8  # focal/ancho; se calibra con /v1/calibrate
_EMA_ALPHA = 0.5
_TRACK_TTL_S = 2.0


@dataclass
class _TrackState:
    distance_m: float
    speed_mps: float
    ts: float
    zone: str | None = None


class FusionEngine:
    """Convierte detecciones crudas en detecciones con dirección, distancia
    suavizada, velocidad de aproximación, TTC y prioridad."""

    def __init__(self, focal_ratio: float = _DEFAULT_FOCAL_RATIO, proximity: ProximityConfig | None = None) -> None:
        self.focal_ratio = focal_ratio
        self.proximity = proximity or ProximityConfig()
        self._tracks: dict[int, _TrackState] = {}

    def update(
        self,
        detections: list[Detection | dict[str, Any]],
        depth_map: np.ndarray | None,
        frame_shape: tuple[int, ...],
    ) -> list[Detection]:
        h, w = frame_shape[:2]
        now = time.monotonic()
        self._tracks = {k: v for k, v in self._tracks.items() if now - v.ts < _TRACK_TTL_S}
        results: list[Detection] = []

        for item in detections:
            det = item if isinstance(item, Detection) else Detection(**item)
            x1, y1, x2, y2 = det.bbox
            cx = (x1 + x2) / 2
            px = cx / max(w, 1)
            direction = 'left' if px < 0.33 else 'right' if px > 0.66 else 'center'
            clock = {'left': 10, 'center': 12, 'right': 2}[direction]
            label = det.label.lower()

            if det.distance_m is not None:
                geometric = det.distance_m
            elif label in GROUND:
                geometric = self._ground_distance(det.bbox, w, h)
            else:
                geometric = self._bbox_distance(label, det.bbox, w, h)
            distance = geometric
            measured = self._sample_depth(depth_map, det.bbox, w, h)
            if measured is not None:
                # Profundidad métrica manda; si discrepa mucho de la geometría se toma la más cercana (conservador).
                ratio = max(measured, geometric) / max(min(measured, geometric), 1e-3)
                distance = min(measured, geometric) if ratio > 2.0 else 0.7 * measured + 0.3 * geometric
            speed, ttc = det.approach_speed_mps, det.ttc_s
            prev = self._tracks.get(det.track_id) if det.track_id is not None else None
            if prev is not None:
                distance = _EMA_ALPHA * distance + (1 - _EMA_ALPHA) * prev.distance_m
                dt = max(1e-3, now - prev.ts)
                inst = (prev.distance_m - distance) / dt
                speed = _EMA_ALPHA * inst + (1 - _EMA_ALPHA) * prev.speed_mps
                ttc = distance / speed if speed > 0.3 else None
            zone = self.proximity.zone(label, float(distance), prev.zone if prev is not None else None)
            if det.track_id is not None:
                self._tracks[det.track_id] = _TrackState(distance, speed or 0.0, now, zone)

            results.append(
                Detection(
                    track_id=det.track_id,
                    label=label,
                    conf=det.conf,
                    bbox=det.bbox,
                    direction=direction,
                    clock=clock,
                    distance_m=round(float(distance), 2),
                    approach_speed_mps=None if speed is None else round(float(speed), 2),
                    ttc_s=None if ttc is None else round(float(ttc), 1),
                    priority=self.priority(label, distance, direction, ttc, zone),
                    zone=zone,
                )
            )
        return results

    @staticmethod
    def _sample_depth(depth_map: np.ndarray | None, bbox: tuple[int, int, int, int], w: int, h: int) -> float | None:
        """Mediana de la profundidad en la zona central-inferior del bbox (evita fondo y bordes)."""
        if depth_map is None:
            return None
        dh, dw = depth_map.shape[:2]
        x1, y1, x2, y2 = bbox
        bw, bh = x2 - x1, y2 - y1
        rx1, rx2 = x1 + 0.3 * bw, x2 - 0.3 * bw
        ry1, ry2 = y1 + 0.4 * bh, y2 - 0.1 * bh
        c1, c2 = int(rx1 / max(w, 1) * dw), max(int(rx1 / max(w, 1) * dw) + 1, int(rx2 / max(w, 1) * dw))
        r1, r2 = int(ry1 / max(h, 1) * dh), max(int(ry1 / max(h, 1) * dh) + 1, int(ry2 / max(h, 1) * dh))
        patch = depth_map[max(0, r1):min(dh, r2), max(0, c1):min(dw, c2)]
        return float(np.median(patch)) if patch.size else None

    def _bbox_distance(self, label: str, bbox: tuple[int, int, int, int], w: int, h: int) -> float:
        x1, y1, x2, y2 = bbox
        focal = self.focal_ratio * w
        by_height = REAL_HEIGHT_M.get(label, _DEFAULT_HEIGHT_M) * focal / max(1, y2 - y1)
        real_w = REAL_WIDTH_M.get(label)
        by_width = real_w * focal / max(1, x2 - x1) if real_w else None
        clipped_v = y1 <= 2 or y2 >= h - 2
        clipped_h = x1 <= 2 or x2 >= w - 2
        # Un recorte hace que esa dimensión parezca más pequeña (=más lejos). Se usa
        # la dimensión no recortada; si ambas lo están, la estimación más cercana.
        if by_width is None or (clipped_h and not clipped_v):
            distance = by_height
        elif clipped_v and not clipped_h:
            distance = by_width
        elif clipped_v and clipped_h:
            distance = min(by_height, by_width)
        else:
            distance = by_height
        return max(0.3, distance)

    def _ground_distance(self, bbox: tuple[int, int, int, int], w: int, h: int) -> float:
        """Distancia a algo que está en el suelo, por dónde toca el suelo en la imagen.

        Supone el celular a ~1,3 m (pecho) y mirando al horizonte: el horizonte cae a media imagen y
        d = altura · focal / (y_base − y_horizonte). Si el celular se inclina, el error crece; es una
        estimación y no una medida. Lo que quede sobre el horizonte se trata como lejano.
        """
        below = bbox[3] - h / 2
        if below < 2:
            return _GROUND_FAR_M
        distance = min(_GROUND_FAR_M, max(0.3, _CAMERA_HEIGHT_M * self.focal_ratio * w / below))
        if bbox[3] >= h - 2:
            # La base se sale por abajo: lo calculado es la distancia MÁXIMA (más cerca no se ve el suelo).
            # Se toma la mitad para no decir que está más lejos de lo que está (factor a ojo, sin medir).
            return max(0.3, distance * _CLIPPED_BASE_FACTOR)
        return distance

    def calibrate(self, label: str, bbox: tuple[int, int, int, int], w: int, known_distance_m: float) -> float:
        """Ajusta la focal para que este bbox corresponda a la distancia real medida."""
        y1, y2 = bbox[1], bbox[3]
        real = REAL_HEIGHT_M.get(label, _DEFAULT_HEIGHT_M)
        self.focal_ratio = known_distance_m * max(1, y2 - y1) / (real * max(1, w))
        self._tracks.clear()
        return self.focal_ratio

    @staticmethod
    def priority(label: str, distance: float, direction: str, ttc: float | None = None, zone: str | None = None) -> str:
        """Prioridad por clase y distancia, con un PISO que depende de la zona de cercanía: lo que está muy cerca no puede quedar en una prioridad baja
        aunque la estimación de distancia (que se infla de cerca) diga otra cosa."""
        base = FusionEngine._base_priority(label, distance, direction, ttc)
        if zone is None or label == 'manhole':
            return base                                    # una tapa puesta nunca es un aviso
        in_path = direction == 'center'
        floor = 'P3'
        if zone == 'muy_cerca':
            critical = label in HAZARDS or label in MOVING or label in GROUND
            if label in HAZARDS or (in_path and critical):
                floor = 'P0'
            elif in_path or label in MOVING:
                floor = 'P1'
        elif zone == 'urgente' and in_path:
            floor = 'P1'
        return min(base, floor)                            # 'P0' < 'P1' < ... como texto: la más urgente de las dos

    @staticmethod
    def _base_priority(label: str, distance: float, direction: str, ttc: float | None = None) -> str:
        in_path = direction == 'center'
        if ttc is not None and ttc < 2.5 and (label in MOVING or label in HAZARDS):
            return 'P0'
        if label in VEHICLES:
            if distance < 3 or (in_path and distance < 5):
                return 'P0' if distance < 3 else 'P1'
            return 'P2' if distance < 8 else 'P3'
        if label == 'manhole':
            # Una tapa puesta no es un peligro y avisarla sería ruido. La clase existe para que el modelo no la confunda con un hueco.
            return 'P3'
        if label == 'pothole':
            # Con el celular a la altura del pecho el suelo más cercano que se ve está a ~2,8 m, así que el
            # umbral genérico de 2,5 m no se activaría nunca. Se avisa a ~5 pasos, a tiempo de frenar.
            return 'P0' if distance < 4.0 else 'P1' if distance < 6.0 else 'P2'
        if label in HAZARDS:
            return 'P0' if distance < 2.5 else 'P1' if distance < 5 else 'P2'
        if label in MOVING:
            if distance < 1.2 and in_path:
                return 'P0'
            if distance < 2 or (in_path and distance < 3):
                return 'P1'
            return 'P2' if distance < 5 else 'P3'
        # Mobiliario y objetos: sólo importan si bloquean el paso.
        if in_path and distance < 1.5:
            return 'P1'
        if in_path and distance < 3:
            return 'P2'
        return 'P3'
