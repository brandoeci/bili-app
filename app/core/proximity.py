"""Zonas de cercanía: decide si algo está MUY CERCA, es URGENTE, solo un AVISO, o está LEJOS, a partir de la distancia ESTIMADA.

Por qué umbrales propios y no la distancia "real": la estimación monocular se pasa de lejos cuanto más cerca está el objeto. Con sillas, carros y
postes medidos con metro (celular a la altura del pecho) la app dijo:
    silla  0,3 / 1,0 / 2,0 m  ->  0,98 / 1,43 / 2,09 m          poste  0,3 / 1,0 / 2,0 m  ->  1,84 / 2,01 / 2,63 m
Casi nunca baja de ~1 m, así que "a menos de un metro" (umbral 0,8) no se activaba nunca. Estos umbrales se fijan sobre la estimación, no sobre la
distancia real: un objeto a ~1 m reales ya cae en "muy cerca".

Dos familias, porque se miden distinto:
  - size:   se estiman por su tamaño en pantalla (persona, silla, carro...). La estimación es fiable desde ~2 m y se infla de cerca.
  - ground: se estiman por donde tocan el suelo (poste, bordillo, hueco, obstáculo, escaleras...). Dependen de cuánto se incline el celular.

VALORES PROVISIONALES: salen de tres puntos por objeto con un solo celular y sin compensar la inclinación. Se ajustan en `.env`
(PROX_SIZE_NEAR_M, PROX_GROUND_NEAR_M, ...) sin tocar el código. Los umbrales de aviso se basan en los rangos de los auxiliares de movilidad
comerciales (1,5 a 4 m) y no en una norma: lo ideal es validarlos con usuarios y un instructor de orientación y movilidad."""
from __future__ import annotations

from dataclasses import dataclass

from app.core.labels import GROUND

ZONES = ('muy_cerca', 'urgente', 'aviso', 'lejos')           # de la más cercana a la más lejana
ZONE_INDEX = {z: i for i, z in enumerate(ZONES)}


@dataclass(frozen=True)
class Thresholds:
    """Límites superiores (m, sobre la estimación) de muy_cerca, urgente y aviso. Más allá de `warn` es 'lejos'."""
    near: float
    urgent: float
    warn: float

    def edges(self) -> tuple[float, float, float]:
        return (self.near, self.urgent, self.warn)


@dataclass(frozen=True)
class ProximityConfig:
    size: Thresholds = Thresholds(near=1.5, urgent=2.0, warn=3.5)
    ground: Thresholds = Thresholds(near=2.1, urgent=3.0, warn=5.0)
    hysteresis: float = 1.15      # para salir de una zona hacia una más lejana hay que pasarse 15 % del límite: evita que parpadee

    def thresholds_for(self, label: str) -> Thresholds:
        return self.ground if label in GROUND else self.size

    def zone(self, label: str, distance_m: float, previous: str | None = None) -> str:
        edges = self.thresholds_for(label).edges()
        index = next((i for i, edge in enumerate(edges) if distance_m < edge), len(edges))
        if previous in ZONE_INDEX:
            prev = ZONE_INDEX[previous]
            # Saliendo hacia una zona más lejana: se queda en la anterior hasta pasar claramente su límite.
            if index > prev and prev < len(edges) and distance_m < edges[prev] * self.hysteresis:
                index = prev
        return ZONES[index]


def spoken_for_zone(zone: str | None) -> str | None:
    """Frase para las dos zonas más cercanas, donde el número no es fiable. None = hablar la distancia como siempre."""
    return {'muy_cerca': 'muy cerca', 'urgente': 'a menos de dos metros'}.get(zone or '')
