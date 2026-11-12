"""Convierte los panoramas de STRIDE (zips) en vistas rectas para entrenar YOLO.

Lee cada imagen directamente del zip (no se descomprime nada en disco), saca 4 vistas en perspectiva
(0, 90, 180 y 270 grados) y las guarda como JPG. Si se interrumpe, al volver a correrlo salta lo ya hecho.

Uso:
  python -I scripts/stride/reproyectar_zips.py ZIP [ZIP ...] --salida CARPETA [--limite N]
                                                  [--fov 80] [--ancho 640] [--alto 480] [--pitch -8]
Las imágenes originales NO se borran: eso se decide aparte, cuando las vistas estén revisadas.
"""
import argparse
import sys
import zipfile
from pathlib import Path

import cv2
import numpy as np

YAWS = (0, 90, 180, 270)


def mapas(w, h, yaw, fov, ancho, alto, pitch):
    """Para cada píxel de la vista, de qué punto del panorama (w x h) se toma."""
    f = (ancho / 2) / np.tan(np.radians(fov) / 2)
    x, y = np.meshgrid(np.arange(ancho) - ancho / 2, np.arange(alto) - alto / 2)
    rayos = np.stack([x, y, np.full_like(x, f)], axis=-1)
    rayos /= np.linalg.norm(rayos, axis=-1, keepdims=True)
    p, q = np.radians(pitch), np.radians(yaw)
    rx = np.array([[1, 0, 0], [0, np.cos(p), -np.sin(p)], [0, np.sin(p), np.cos(p)]])
    ry = np.array([[np.cos(q), 0, np.sin(q)], [0, 1, 0], [-np.sin(q), 0, np.cos(q)]])
    d = rayos @ (ry @ rx).T
    lon = np.arctan2(d[..., 0], d[..., 2])
    lat = np.arcsin(np.clip(d[..., 1], -1, 1))
    return (((lon / (2 * np.pi) + 0.5) * w).astype(np.float32), ((lat / np.pi + 0.5) * h).astype(np.float32))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('zips', nargs='+')
    ap.add_argument('--salida', required=True)
    ap.add_argument('--limite', type=int, default=0, help='máximo de panoramas por zip (0 = todos)')
    ap.add_argument('--fov', type=float, default=80)
    ap.add_argument('--ancho', type=int, default=640)
    ap.add_argument('--alto', type=int, default=480)
    ap.add_argument('--pitch', type=float, default=-8)
    a = ap.parse_args()
    out = Path(a.salida)
    out.mkdir(parents=True, exist_ok=True)

    cache = {}  # (w, h) -> mapas por yaw; son iguales para todos los panoramas del mismo tamaño
    hechas = fallidas = 0
    for zpath in a.zips:
        with zipfile.ZipFile(zpath) as z:
            nombres = [i.filename for i in z.infolist() if not i.is_dir() and i.filename.lower().endswith('.jpg')]
            if a.limite:
                nombres = nombres[: a.limite]
            for n, nombre in enumerate(nombres, 1):
                base = Path(nombre).stem
                if all((out / f'{base}_yaw{y}.jpg').exists() for y in YAWS):
                    continue
                try:
                    # Se decodifica a la mitad del tamaño: basta para vistas de 640 px y gasta 4 veces menos memoria
                    pano = cv2.imdecode(np.frombuffer(z.read(nombre), np.uint8), cv2.IMREAD_REDUCED_COLOR_2)
                    if pano is None:
                        raise ValueError('no se pudo decodificar')
                    h, w = pano.shape[:2]
                    if (w, h) not in cache:
                        cache = {(w, h): {y: mapas(w, h, y, a.fov, a.ancho, a.alto, a.pitch) for y in YAWS}}
                    for y in YAWS:
                        mx, my = cache[(w, h)][y]
                        vista = cv2.remap(pano, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_WRAP)
                        cv2.imencode('.jpg', vista, [cv2.IMWRITE_JPEG_QUALITY, 90])[1].tofile(str(out / f'{base}_yaw{y}.jpg'))
                    hechas += 1
                except Exception as exc:  # una imagen mala no debe frenar las otras 10 000
                    fallidas += 1
                    print('FALLÓ', nombre, type(exc).__name__, exc, file=sys.stderr)
                if n % 50 == 0:
                    print(f'{Path(zpath).name}: {n}/{len(nombres)}', flush=True)
        print('zip terminado:', Path(zpath).name, '| panoramas procesados hasta ahora:', hechas, '| fallidas:', fallidas, flush=True)
    print('LISTO. panoramas:', hechas, '| fallidas:', fallidas)


if __name__ == '__main__':
    main()
