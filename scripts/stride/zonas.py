"""Reserva zonas geográficas completas de STRIDE para usarlas SOLO como examen, nunca para entrenar.

Por qué por zonas y no por fotos sueltas: las vistas de una misma cuadra son casi idénticas, y si unas se entrenan y otras
se usan de examen, el examen sale inflado (en el dataset v2 más de la mitad del test tenía copias en el train).

Regla: la ciudad se parte en cuadros de 0.03 grados (~3,3 km). Con semilla fija se reserva ~15 % de los panoramas en cuadros
completos. Alrededor de cada cuadro reservado hay una franja de 0.0015 grados (~165 m) que no se usa para nada (buffer).

Uso en otros scripts:   from zonas import zona;  zona(nombre_de_archivo) -> 'reservada' | 'buffer' | 'entrenable'
Generar listas:         python -I scripts/stride/zonas.py CARPETA_CON_VISTAS SALIDA
El nombre del archivo trae las coordenadas:  <idPanorama>_<lat>_<lng>_<año>_yawNNN.jpg
"""
import json
import random
import re
import sys
from collections import Counter
from pathlib import Path

PAT = re.compile(r'^(.*)_(-?\d+\.\d+)_(-?\d+\.\d+)_(\d{4})_yaw(\d+)\.jpg$')
TILE = 0.03
BUFFER = 0.0015
FRACCION = 0.15
SEMILLA = 2026
_RESERVADOS = None


def coords(nombre: str):
    m = PAT.match(Path(nombre).name)
    return (float(m.group(2)), float(m.group(3))) if m else None


def tile_de(lat: float, lng: float):
    return (int(lat // TILE), int(lng // TILE))


def elegir_tiles(todas: list[tuple[float, float]]) -> set:
    cuenta = Counter(tile_de(a, b) for a, b in todas)
    orden = sorted(cuenta)
    random.Random(SEMILLA).shuffle(orden)
    elegidos, total = set(), 0
    meta = FRACCION * len(todas)
    for t in orden:
        if total >= meta:
            break
        elegidos.add(t)
        total += cuenta[t]
    return elegidos


def cargar(path: Path = Path(__file__).with_name('zonas_reservadas.json')) -> set:
    global _RESERVADOS
    if _RESERVADOS is None:
        _RESERVADOS = {tuple(t) for t in json.loads(path.read_text())['tiles']}
    return _RESERVADOS


def zona(nombre: str) -> str:
    c = coords(nombre)
    if c is None:
        raise ValueError(f'nombre sin coordenadas: {nombre}')
    res = cargar()
    lat, lng = c
    if tile_de(lat, lng) in res:
        return 'reservada'
    for dla in (-BUFFER, 0, BUFFER):
        for dln in (-BUFFER, 0, BUFFER):
            if tile_de(lat + dla, lng + dln) in res:
                return 'buffer'
    return 'entrenable'


def main() -> None:
    carpeta, salida = Path(sys.argv[1]), Path(sys.argv[2])
    salida.mkdir(parents=True, exist_ok=True)
    nombres = sorted(p.name for p in carpeta.glob('*.jpg'))
    pos = {}
    for n in nombres:
        c = coords(n)
        if c:
            pos[PAT.match(n).group(1)] = c
    tiles = elegir_tiles(list(pos.values()))
    destino = Path(__file__).with_name('zonas_reservadas.json')
    destino.write_text(json.dumps({'tile_grados': TILE, 'buffer_grados': BUFFER, 'fraccion': FRACCION, 'semilla': SEMILLA,
                                   'tiles': sorted(tiles)}, indent=1), encoding='utf-8')
    global _RESERVADOS
    _RESERVADOS = tiles
    listas = {'reservada': [], 'buffer': [], 'entrenable': []}
    for n in nombres:
        listas[zona(n)].append(n)
    for k, v in listas.items():
        (salida / f'{k}.txt').write_text('\n'.join(v), encoding='utf-8')
    paisaje = Counter()
    for n in nombres:
        paisaje[(zona(n), PAT.match(n).group(4))] += 1
    print(f'tiles reservados: {len(tiles)} | vistas: ' + ' | '.join(f'{k}={len(v)} ({100 * len(v) / len(nombres):.1f} %)' for k, v in listas.items()))
    print('panoramas reservados:', len({PAT.match(n).group(1) for n in listas['reservada']}))
    print('años en la zona reservada:', {y: c for (z, y), c in sorted(paisaje.items()) if z == 'reservada'})
    print('manifiesto:', destino)


if __name__ == '__main__':
    main()
