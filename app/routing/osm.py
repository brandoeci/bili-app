"""Cruces de calle de Bogotá, de OpenStreetMap (© colaboradores de OpenStreetMap, licencia ODbL).

Se consultan en un archivo local (scripts/osm/descargar_cruces.py) y no en el servidor público de Overpass: este tarda
decenas de segundos y la persona no puede esperar callada. Con el archivo local la consulta es instantánea y no
depende de la red.
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path

from app.routing.base import ProviderError
from app.routing.models import Cruce, LatLng
from app.routing.polyline import distancia_m

FUSION_M = 12.0  # un semáforo y un cruce a menos de esto son el mismo cruce
CELDA_DEG = 0.002  # ~220 m: tamaño de las celdas del índice
M_POR_GRADO = 111195.0


def clasificar(tags: dict) -> str:
    if tags.get('highway') == 'traffic_signals' or tags.get('crossing') == 'traffic_signals' or tags.get('crossing:signals') == 'yes':
        return 'semaforo'
    if tags.get('crossing') in {'zebra', 'marked', 'uncontrolled'} or tags.get('crossing_ref') == 'zebra':
        return 'cebra'
    return 'cruce'


def fusionar(elementos: list[dict]) -> list[Cruce]:
    """Une nodos del mismo cruce. Gana el tipo más informativo: semáforo > cebra > cruce."""
    rango = {'semaforo': 0, 'cebra': 1, 'cruce': 2}
    candidatos = sorted(
        (Cruce(lat=e['lat'], lng=e['lon'], tipo=clasificar(e.get('tags', {}))) for e in elementos if 'lat' in e and 'lon' in e),
        key=lambda c: rango[c.tipo],
    )
    salida: list[Cruce] = []
    for c in candidatos:
        if all(distancia_m(LatLng(lat=c.lat, lng=c.lng), LatLng(lat=o.lat, lng=o.lng)) > FUSION_M for o in salida):
            salida.append(c)
    return salida


def _celda(lat: float, lng: float) -> tuple[int, int]:
    return math.floor(lat / CELDA_DEG), math.floor(lng / CELDA_DEG)


def _dist_a_segmento_m(p: tuple[float, float], a: LatLng, b: LatLng) -> float:
    """Distancia de p=(lat,lng) al segmento ab, en metros (plano local)."""
    kx = M_POR_GRADO * math.cos(math.radians(p[0]))
    ax, ay = (a.lng - p[1]) * kx, (a.lat - p[0]) * M_POR_GRADO
    bx, by = (b.lng - p[1]) * kx, (b.lat - p[0]) * M_POR_GRADO
    dx, dy = bx - ax, by - ay
    largo2 = dx * dx + dy * dy
    t = 0.0 if largo2 == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / largo2))
    return math.hypot(ax + t * dx, ay + t * dy)


class CrucesLocales:
    def __init__(self, nodos: list[dict]):
        self._grid: dict[tuple[int, int], list[dict]] = defaultdict(list)
        for n in nodos:
            self._grid[_celda(n['lat'], n['lon'])].append(n)
        self.total = len(nodos)

    @classmethod
    def desde_archivo(cls, ruta: Path) -> 'CrucesLocales':
        try:
            data = json.loads(Path(ruta).read_text(encoding='utf-8'))
            return cls(data['nodos'])
        except (OSError, ValueError, KeyError) as exc:
            raise ProviderError(f'no pude leer el archivo de cruces ({type(exc).__name__})') from exc

    def _candidatos(self, a: LatLng, b: LatLng, radio_m: float) -> list[dict]:
        margen = radio_m / M_POR_GRADO + CELDA_DEG
        i0, j0 = _celda(min(a.lat, b.lat) - margen, min(a.lng, b.lng) - margen)
        i1, j1 = _celda(max(a.lat, b.lat) + margen, max(a.lng, b.lng) + margen)
        return [n for i in range(i0, i1 + 1) for j in range(j0, j1 + 1) for n in self._grid.get((i, j), ())]

    def cruces_cerca(self, puntos: list[LatLng], radio_m: float = 15.0) -> list[Cruce]:
        vistos: dict[int, dict] = {}
        segmentos = list(zip(puntos, puntos[1:])) or [(p, p) for p in puntos[:1]]
        for a, b in segmentos:
            for n in self._candidatos(a, b, radio_m):
                if id(n) not in vistos and _dist_a_segmento_m((n['lat'], n['lon']), a, b) <= radio_m:
                    vistos[id(n)] = n
        return fusionar(list(vistos.values()))
