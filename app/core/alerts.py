from __future__ import annotations

import itertools
import time
from dataclasses import dataclass

from app.core.labels import LABELS_ES, label_es  # noqa: F401  (LABELS_ES se reexporta por compatibilidad)
from app.core.proximity import ZONE_INDEX, spoken_for_zone
from app.schemas import Alert, Detection

_RANK = {'P0': 0, 'P1': 1, 'P2': 2, 'P3': 3}
# Bandas de cercanía: (límite superior en metros, índice). Más bajo = más cerca.
_BAND_EDGES = (1.2, 2.5, 4.5)
_NUMBERS = {1: 'un', 2: 'dos', 3: 'tres', 4: 'cuatro', 5: 'cinco', 6: 'seis', 7: 'siete', 8: 'ocho', 9: 'nueve', 10: 'diez'}
_FORGET_AFTER_S = 3.0


def _band(distance_m: float) -> int:
    for index, edge in enumerate(_BAND_EDGES):
        if distance_m < edge:
            return index
    return len(_BAND_EDGES)


def _band_of(det: Detection) -> int:
    """Banda de cercanía de una detección: su zona si la trae (ver proximity.py); si no, la banda por distancia de siempre."""
    if det.zone is not None:
        return ZONE_INDEX[det.zone]
    return _band(det.distance_m or 99)


@dataclass
class _Memory:
    first_seen: float
    last_seen: float
    frames: int = 1
    announced_at: float | None = None
    announced_band: int = 99
    announced_direction: str = ''
    announced_priority: str = 'P3'
    announced_conducta: str | None = None


class AlertManager:
    """Decide *cuándo* hablar. Una alerta se emite sólo cuando aporta información
    nueva: objeto nuevo, más cerca, cambió de lado, se acerca rápido o recordatorio
    espaciado de un peligro crítico persistente. Un objeto estático no se repite."""

    def __init__(
        self,
        critical_distance_m: float = 2.5,
        release_distance_m: float = 3.2,
        cooldown_s: float = 4.0,
        min_frames: int = 1,
        max_speech_rate_s: float = 1.5,
        reminder_s: float = 12.0,
    ):
        self.critical_distance_m = critical_distance_m
        self.release_distance_m = release_distance_m
        self.cooldown_s = cooldown_s
        self.min_frames = max(1, min_frames)
        self.max_speech_rate_s = max_speech_rate_s
        self.reminder_s = reminder_s
        self._memory: dict[object, _Memory] = {}
        self._last_emit_at = -1e9
        self._ids = itertools.count(1)

    def evaluate(self, detections: list[Detection], now: float | None = None) -> list[Alert]:
        now = time.monotonic() if now is None else now
        wall = time.time()
        self._memory = {k: m for k, m in self._memory.items() if now - m.last_seen < _FORGET_AFTER_S}

        candidates: list[tuple[int, float, Detection, str, _Memory]] = []
        for det in detections:
            if det.distance_m is None or det.priority == 'P3' or det.conducta == 'callar':
                continue
            key: object = det.track_id if det.track_id is not None else (det.label, det.direction)
            mem = self._memory.get(key)
            if mem is None:
                mem = self._memory[key] = _Memory(first_seen=now, last_seen=now)
            else:
                mem.frames += 1
                mem.last_seen = now

            reason = self._should_announce(det, mem, now)
            if reason:
                candidates.append((_RANK[det.priority], det.distance_m, det, reason, mem))

        candidates.sort(key=lambda c: (c[0], c[1]))
        alerts: list[Alert] = []
        for rank, _, det, reason, mem in candidates[:2]:
            # Límite global de habla; los P0 siempre pasan.
            if rank > 0 and now - self._last_emit_at < self.max_speech_rate_s:
                continue
            if rank > 1 and alerts:
                continue  # P2 nunca acompaña a una alerta más urgente
            alerts.append(
                Alert(
                    id=f'alert-{next(self._ids)}',
                    ts=wall,
                    # Pedir que se detenga es información de seguridad: prioridad máxima de voz (paper, "dos voces que no pueden hablar a la vez").
                    priority='P0' if det.conducta == 'incertidumbre' else det.priority,
                    text=self._phrase_for(det, reason),
                    source='reflex',
                    track_id=det.track_id,
                )
            )
            mem.announced_at = now
            mem.announced_band = _band_of(det)
            mem.announced_direction = det.direction
            mem.announced_priority = det.priority
            mem.announced_conducta = det.conducta
            self._last_emit_at = now
        return alerts

    def _should_announce(self, det: Detection, mem: _Memory, now: float) -> str | None:
        if det.priority != 'P0' and mem.frames < self.min_frames:
            return None  # filtra parpadeos de un solo frame
        band = _band_of(det)
        if mem.announced_at is None:
            return 'new'
        since = now - mem.announced_at
        distance = det.distance_m or 99
        if det.zone is not None:
            # Con zonas la histéresis ya la hace la fusión: si pasó a una zona más lejana, se re-arma y volverá a avisar al acercarse de nuevo.
            if band > mem.announced_band:
                mem.announced_band = band
        # Histéresis: sólo se "re-arma" una banda si el objeto se alejó claramente de ella.
        elif mem.announced_band < len(_BAND_EDGES) and distance > _BAND_EDGES[mem.announced_band] * 1.25:
            mem.announced_band = band
        if mem.announced_conducta == 'incertidumbre' and det.conducta == 'avisar' and since >= 1.0:
            return 'confirmed'   # se pidió detenerse sin saber qué era; ahora el modelo lo reconoce: se nombra
        if _RANK[det.priority] < _RANK[mem.announced_priority] and since >= 1.0:
            return 'escalated'
        if band < mem.announced_band and since >= 1.0:
            return 'closer'
        if det.ttc_s is not None and det.ttc_s < 3.0 and since >= 2.0:
            return 'approaching'
        if det.direction != mem.announced_direction and since >= self.cooldown_s:
            return 'moved'
        if det.priority == 'P0' and since >= self.reminder_s:
            return 'reminder'
        return None

    @staticmethod
    def spoken_distance(distance_m: float) -> str:
        if distance_m < 0.8:
            return 'a menos de un metro'
        halves = round(distance_m * 2) / 2
        whole = int(halves)
        if halves > 10:
            return 'a más de diez metros'
        if halves == 1:
            return 'a un metro'
        if halves == 1.5:
            return 'a metro y medio'
        if halves == whole:
            return f'a {_NUMBERS[whole]} metros'
        return f'a {_NUMBERS[whole]} metros y medio'

    @classmethod
    def _phrase_for(cls, det: Detection, reason: str = 'new') -> str:
        side = {'left': 'a su izquierda', 'right': 'a su derecha'}.get(det.direction, 'al frente')
        if det.conducta == 'incertidumbre':
            # QA-3: se pide detenerse SIN nombrar la clase (la confianza no alcanza para afirmarla) y sin una distancia que no es fiable.
            return f'Deténgase: hay algo {side} y no estoy seguro de qué es'
        label = label_es(det.label)
        # En las dos zonas más cercanas el número no es fiable (la estimación se infla): se dice "muy cerca" o "a menos de dos metros".
        dist = spoken_for_zone(det.zone) or (cls.spoken_distance(det.distance_m) if det.distance_m is not None else '')
        approaching = (det.ttc_s is not None and det.ttc_s < 4.0) or (det.approach_speed_mps or 0) > 0.6
        tail = ', se acerca' if approaching else ''
        note = f'. {det.note}' if det.note and reason != 'reminder' else ''
        if reason == 'reminder':
            return f'Sigue {label} {side}, {dist}'.strip()
        if reason == 'closer':
            return f'{label.capitalize()} {side}, ahora {dist}{tail}{note}'
        if det.priority == 'P0':
            return f'Cuidado: {label} {side}, {dist}{tail}{note}'
        return f'{label.capitalize()} {side}, {dist}{tail}{note}'
