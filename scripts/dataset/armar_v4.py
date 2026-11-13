"""Arma el dataset v4 = dataset actual (v2) + fuentes nuevas de escaleras, sin tocar el dataset original.

- Parte de una copia (enlaces duros: no duplica espacio) de --base y le suma las fuentes nuevas ya mapeadas a las clases de Bili.
- El TEST queda idéntico al original, para que v2 y v4 se comparen con el mismo examen.
- Las imágenes nuevas de 'valid' van al val del v4; las de 'test' de las fuentes nuevas se apartan en --heldout
  (examen aparte, solo de escaleras nuevas) y NO se entrenan.
- Se descarta toda imagen nueva que sea (casi) copia de una del test o del val originales (hash perceptual dHash).

Uso:
  python scripts/dataset/armar_v4.py --base data/bili-dataset --out data/bili-dataset-v4 --heldout data/stairs-heldout \
      --map stairs-blind:0=stairs --map stairs-blind:1=stairs --map stairs-blind:2=stairs \
      data/raw/stairs-blind data/raw/staircase-uta
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from collections import Counter
from pathlib import Path

import cv2
import numpy as np
import yaml

sys.path.insert(0, str(Path(__file__).parent))
import prepare_dataset as pd  # noqa: E402

IMG = {'.jpg', '.jpeg', '.png', '.bmp', '.webp'}


def enlazar(src: Path, dst: Path) -> None:
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def dhash(path: Path) -> int | None:
    img = cv2.imdecode(np.fromfile(str(path), np.uint8), cv2.IMREAD_GRAYSCALE)
    if img is None:
        return None
    p = cv2.resize(img, (9, 8), interpolation=cv2.INTER_AREA)
    bits = (p[:, 1:] > p[:, :-1]).flatten()
    return int(''.join('1' if b else '0' for b in bits), 2)


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count('1')


def contar(carpeta: Path, split: str) -> Counter:
    c = Counter()
    for lab in (carpeta / 'labels' / split).glob('*.txt'):
        for ln in lab.read_text().splitlines():
            if ln.split():
                c[pd.BILI_CLASSES[int(ln.split()[0])]] += 1
    return c


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('sources', nargs='+', type=Path)
    ap.add_argument('--base', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--heldout', type=Path, required=True)
    ap.add_argument('--map', action='append', default=[])
    ap.add_argument('--umbral', type=int, default=4, help='distancia de Hamming (de 64 bits) para considerar copia')
    a = ap.parse_args()
    if a.out.exists() or a.heldout.exists():
        sys.exit('La salida ya existe: no la piso. Bórrela a mano si quiere rehacerla.')

    # 1) fuentes nuevas, mapeadas a las clases de Bili, en un lugar temporal
    tmp = a.out.parent / '_v4_nuevas'
    pd.build(a.sources, tmp, 0.0, 0, pd.parse_overrides(a.map))

    # 2) hashes del test y val originales
    originales = {}
    for split in ('test', 'val'):
        for p in (a.base / 'images' / split).iterdir():
            if p.suffix.lower() in IMG and (h := dhash(p)) is not None:
                originales[p.name] = (split, h)
    print(f'\nhashes de test+val originales: {len(originales)}')

    # 3) copia de la base con enlaces duros
    for split in ('train', 'val', 'test'):
        for kind in ('images', 'labels'):
            (a.out / kind / split).mkdir(parents=True)
            for f in (a.base / kind / split).iterdir():
                enlazar(f, a.out / kind / split / f.name)
    shutil.copy2(a.base / 'data.yaml', a.out / 'data.yaml')
    antes = contar(a.out, 'train')

    # 4) sumar lo nuevo
    for kind in ('images', 'labels'):
        (a.heldout / kind / 'val').mkdir(parents=True)
    descartes = Counter()
    sumadas = Counter()
    for split in ('train', 'val', 'test'):
        for p in sorted((tmp / 'images' / split).iterdir()):
            h = dhash(p)
            copia = None
            if h is not None:
                for nombre, (s, ho) in originales.items():
                    if hamming(h, ho) <= a.umbral:
                        copia = (nombre, s)
                        break
            if copia:
                descartes[f'copia de una imagen del {copia[1]} original'] += 1
                continue
            lab = tmp / 'labels' / split / (p.stem + '.txt')
            if split == 'test':  # examen aparte, no se entrena
                enlazar(p, a.heldout / 'images' / 'val' / p.name)
                enlazar(lab, a.heldout / 'labels' / 'val' / lab.name)
                sumadas['heldout'] += 1
            else:
                enlazar(p, a.out / 'images' / split / p.name)
                enlazar(lab, a.out / 'labels' / split / lab.name)
                sumadas[split] += 1
    (a.heldout / 'data.yaml').write_text(yaml.safe_dump({
        'train': 'images/val', 'val': 'images/val', 'test': 'images/val',
        'names': {i: c for i, c in enumerate(pd.BILI_CLASSES)}}, sort_keys=False), encoding='utf-8')
    shutil.rmtree(tmp)

    # 5) informe
    despues = contar(a.out, 'train')
    print('\nImagenes nuevas sumadas:', dict(sumadas), '| descartadas:', dict(descartes))
    print('\nInstancias en TRAIN (antes -> despues):')
    for c in pd.BILI_CLASSES:
        print(f'  {c:<12} {antes[c]:>7} -> {despues[c]:>7}   (+{despues[c] - antes[c]})')
    print('\nExamen aparte (heldout, escaleras nuevas):', dict(contar(a.heldout, 'val')))
    base_test = sorted(p.name for p in (a.base / 'images' / 'test').iterdir())
    v4_test = sorted(p.name for p in (a.out / 'images' / 'test').iterdir())
    print('TEST del v4 identico al original:', base_test == v4_test, f'({len(v4_test)} imagenes)')


if __name__ == '__main__':
    main()
