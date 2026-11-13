"""Quita de val y test (y del examen aparte) las imágenes con una copia casi idéntica en el train.

Se encontró que más de la mitad del test y del val del v2 tenían copias en el train: un examen así sobreestima el modelo.
Con huellas perceptuales dHash (decodificación reducida, igual para todas las imágenes) se mide la distancia de cada imagen
de val/test al train más cercano y se quita la que quede a distancia <= --umbral. Solo se borran enlaces del v4:
los archivos originales siguen intactos en el dataset de origen.

Uso: python -I scripts/dataset/limpiar_v4.py --v4 data/bili-dataset-v4 --heldout data/stairs-heldout [--umbral 8]
"""
from __future__ import annotations

import argparse
import time
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

IMG = {'.jpg', '.jpeg', '.png', '.bmp', '.webp'}
CLASES = ['pothole', 'manhole', 'curb', 'stairs_down', 'stairs_up', 'stairs', 'pole', 'obstacle']


def _hh(g: np.ndarray) -> int:
    p = cv2.resize(g, (9, 8), interpolation=cv2.INTER_AREA)
    v = 0
    for b in (p[:, 1:] > p[:, :-1]).flatten():
        v = (v << 1) | int(b)
    return v


def dhash(path: Path) -> tuple[int, int, bool]:
    """(huella normal, huella del espejo horizontal, legible). El espejo detecta los aumentos con volteo."""
    img = cv2.imdecode(np.fromfile(str(path), np.uint8), cv2.IMREAD_REDUCED_GRAYSCALE_4)
    if img is None:
        return 0, 0, False
    return _hh(img), _hh(cv2.flip(img, 1)), True


def hashes(carpeta: Path):
    ps = sorted(p for p in carpeta.iterdir() if p.suffix.lower() in IMG)
    h, hm, ok = zip(*(dhash(p) for p in ps)) if ps else ((), (), ())
    return ps, np.array(h, dtype=np.uint64), np.array(hm, dtype=np.uint64), np.array(ok, dtype=bool)


def distancias(h: np.ndarray, hm: np.ndarray, ok: np.ndarray, train: np.ndarray) -> np.ndarray:
    """Distancia al train más cercano, mirando la imagen tal cual y su espejo."""
    d = np.full(len(h), 64, dtype=np.int32)
    for i in range(len(h)):
        if ok[i]:
            d[i] = int(min(np.bitwise_count(train ^ h[i]).min(), np.bitwise_count(train ^ hm[i]).min()))
    return d


def contar(raiz: Path, split: str) -> Counter:
    c = Counter()
    for lab in (raiz / 'labels' / split).glob('*.txt'):
        for ln in lab.read_text().splitlines():
            if ln.split():
                c[CLASES[int(ln.split()[0])]] += 1
    return c


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--v4', type=Path, required=True)
    ap.add_argument('--heldout', type=Path, required=True)
    ap.add_argument('--umbral', type=int, default=8)
    a = ap.parse_args()
    t0 = time.time()
    _, htr, _, oktr = hashes(a.v4 / 'images' / 'train')
    train = htr[oktr]
    print(f'train: {len(train)} huellas ({time.time() - t0:.0f} s)', flush=True)

    objetivos = [('val', a.v4, a.v4 / 'images' / 'val'), ('test', a.v4, a.v4 / 'images' / 'test'),
                 ('heldout', a.heldout, a.heldout / 'images' / 'val')]
    for nombre, raiz, carpeta in objetivos:
        ps, h, hm, ok = hashes(carpeta)
        d = distancias(h, hm, ok, train)
        malas = [p for p, x in zip(ps, d) if x <= a.umbral]
        previo = contar(raiz, 'val' if nombre == 'heldout' else nombre)
        registro = raiz / f'quitadas_{nombre}.txt'
        with open(registro, 'a', encoding='utf-8') as f:  # se agrega: así se conserva lo quitado en pasadas anteriores
            f.write(''.join(p.name + '\n' for p in malas))
        for p in malas:
            lab = raiz / 'labels' / carpeta.name / (p.stem + '.txt')
            p.unlink()
            lab.unlink(missing_ok=True)
        despues = contar(raiz, 'val' if nombre == 'heldout' else nombre)
        print(f'\n{nombre}: {len(ps)} -> {len(ps) - len(malas)} imágenes (quitadas {len(malas)}, {100 * len(malas) / max(1, len(ps)):.0f} %) | registro: {registro.name}')
        print('  instancias por clase (antes -> después):')
        for c in CLASES:
            if previo[c] or despues[c]:
                print(f'    {c:12s} {previo[c]:6d} -> {despues[c]:6d}' + ('   <-- POCAS para medir' if despues[c] < 30 else ''))
    print('\nlisto', f'({time.time() - t0:.0f} s)')


if __name__ == '__main__':
    main()
