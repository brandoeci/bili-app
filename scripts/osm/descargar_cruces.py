"""Descarga los cruces de calle y semáforos de Bogotá (OpenStreetMap) a un archivo local.

Los datos son de OpenStreetMap, © colaboradores de OpenStreetMap, licencia ODbL (https://www.openstreetmap.org/copyright).
Uso:  python scripts/osm/descargar_cruces.py [salida.json]
"""
from __future__ import annotations

import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

URL = 'https://overpass-api.de/api/interpreter'
# Caja que cubre el área urbana de Bogotá (sur, oeste, norte, este).
BBOX = '4.46,-74.25,4.84,-73.99'
QUERY = (
    '[out:json][timeout:300][maxsize:536870912];('
    f'node["highway"="crossing"]({BBOX});'
    f'node["highway"="traffic_signals"]({BBOX});'
    ');out;'
)


def main() -> int:
    salida = Path(sys.argv[1] if len(sys.argv) > 1 else 'data/osm/bogota_cruces.json')
    salida.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(
        URL,
        data=urllib.parse.urlencode({'data': QUERY}).encode(),
        headers={'User-Agent': 'bili-app/0.1 (proyecto universitario; descarga unica)'},
    )
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=330) as r:
        data = json.load(r)
    nodos = [
        {'lat': e['lat'], 'lon': e['lon'], 'tags': {k: v for k, v in e.get('tags', {}).items() if k in {'highway', 'crossing', 'crossing:signals', 'crossing_ref'}}}
        for e in data.get('elements', [])
        if 'lat' in e
    ]
    salida.write_text(json.dumps({'fuente': 'OpenStreetMap (ODbL)', 'bbox': BBOX, 'nodos': nodos}, ensure_ascii=False), encoding='utf-8')
    print(f'{len(nodos)} nodos en {time.time() - t0:.0f} s -> {salida} ({salida.stat().st_size / 1e6:.1f} MB)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
