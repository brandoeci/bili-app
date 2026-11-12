from __future__ import annotations

import math

from app.routing.models import LatLng


def decode_polyline(encoded: str) -> list[LatLng]:
    """Decodifica el formato de polilínea de Google (precisión 1e-5)."""
    puntos: list[LatLng] = []
    i, lat, lng = 0, 0, 0
    n = len(encoded)
    while i < n:
        for eje in (0, 1):
            resultado, shift = 0, 0
            while True:
                if i >= n:
                    raise ValueError('polilínea truncada')
                b = ord(encoded[i]) - 63
                i += 1
                resultado |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            delta = ~(resultado >> 1) if resultado & 1 else resultado >> 1
            if eje == 0:
                lat += delta
            else:
                lng += delta
        puntos.append(LatLng(lat=lat / 1e5, lng=lng / 1e5))
    return puntos


def distancia_m(a: LatLng, b: LatLng) -> float:
    r = 6371000.0
    p1, p2 = math.radians(a.lat), math.radians(b.lat)
    dphi, dl = p2 - p1, math.radians(b.lng - a.lng)
    h = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))
