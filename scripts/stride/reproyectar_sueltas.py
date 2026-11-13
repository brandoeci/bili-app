"""Convierte panoramas STRIDE sueltos (jpg en una carpeta, bajados a mano) en vistas rectas, separando por zona geográfica.

  <salida>/entrenable/  -> pueden usarse para entrenar
  <salida>/reservada/   -> zona de examen (NO entrenar) y franja de seguridad (tampoco se usa): van en reservada/ y buffer/

Los originales no se tocan. Un nombre con "(1)" (descarga repetida) se omite si ya está el original.

Uso: python -I scripts/stride/reproyectar_sueltas.py CARPETA_PANORAMAS CARPETA_SALIDA
"""
import re
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from reproyectar_zips import YAWS, mapas  # noqa: E402
from zonas import zona  # noqa: E402

PAT = re.compile(r'^(.+?)_(-?\d+\.\d+)_(-?\d+\.\d+)_(\d{4})( \(\d+\))?\.jpg$')


def main() -> None:
    entrada, salida = Path(sys.argv[1]), Path(sys.argv[2])
    cache = {}
    cuenta = {'entrenable': 0, 'reservada': 0, 'buffer': 0}
    repetidos = fallidas = ya = 0
    vistos = set()
    for p in sorted(entrada.glob('*.jpg')):
        m = PAT.match(p.name)
        if not m:
            continue
        base = f'{m.group(1)}_{m.group(2)}_{m.group(3)}_{m.group(4)}'
        if base in vistos:
            repetidos += 1
            continue
        vistos.add(base)
        z = zona(f'{base}_yaw0.jpg')
        destino = salida / z
        destino.mkdir(parents=True, exist_ok=True)
        if all((destino / f'{base}_yaw{y}.jpg').exists() for y in YAWS):
            ya += 1  # ya convertido en una corrida anterior
            continue
        try:
            pano = cv2.imdecode(np.fromfile(str(p), np.uint8), cv2.IMREAD_REDUCED_COLOR_2)
            if pano is None:
                raise ValueError('no se pudo decodificar')
            h, w = pano.shape[:2]
            if (w, h) not in cache:
                cache = {(w, h): {y: mapas(w, h, y, 80, 640, 480, -8) for y in YAWS}}
            for y in YAWS:
                mx, my = cache[(w, h)][y]
                vista = cv2.remap(pano, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_WRAP)
                cv2.imencode('.jpg', vista, [cv2.IMWRITE_JPEG_QUALITY, 90])[1].tofile(str(destino / f'{base}_yaw{y}.jpg'))
            cuenta[z] += 1
        except Exception as exc:
            fallidas += 1
            print('FALLÓ', p.name, type(exc).__name__, exc, file=sys.stderr)
    print('panoramas convertidos:', cuenta, '| repetidos omitidos:', repetidos, '| ya convertidos antes:', ya, '| fallidos:', fallidas)
    print('vistas NUEVAS (x4):', {k: v * 4 for k, v in cuenta.items()})


if __name__ == '__main__':
    main()
