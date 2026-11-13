"""Une stairs_down, stairs_up y stairs en una sola clase 'stairs' en un dataset ya armado (formato YOLO).

Por qué: con una sola clase hay más ejemplos para aprender y para medir (en el test limpio había 4 y 18 de las de dirección).
La dirección (subir o bajar) se decide aparte, con la profundidad.

Reindexa de 8 a 6 clases: pothole, manhole, curb, stairs, pole, obstacle.

CUIDADO: si las etiquetas son enlaces duros a otro dataset (como en bili-dataset-v4), escribir encima las alteraría también
en el original. Cada etiqueta se reescribe en un archivo nuevo y se reemplaza la entrada (os.replace): el original no cambia.
Con --original se comprueba que sus etiquetas quedaron idénticas.

Uso: python -I scripts/dataset/unir_escaleras.py RAIZ [RAIZ ...] [--original data/bili-dataset]
"""
from __future__ import annotations

import argparse
import os
from collections import Counter
from pathlib import Path

import yaml

VIEJAS = ['pothole', 'manhole', 'curb', 'stairs_down', 'stairs_up', 'stairs', 'pole', 'obstacle']
NUEVAS = ['pothole', 'manhole', 'curb', 'stairs', 'pole', 'obstacle']
MAPA = {i: NUEVAS.index('stairs' if n.startswith('stairs') else n) for i, n in enumerate(VIEJAS)}


def histograma(raiz: Path) -> Counter:
    c = Counter()
    for lab in raiz.glob('labels/*/*.txt'):
        for ln in lab.read_text().splitlines():
            if ln.split():
                c[int(ln.split()[0])] += 1
    return c


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('raices', nargs='+', type=Path)
    ap.add_argument('--original', type=Path)
    a = ap.parse_args()
    antes_original = histograma(a.original) if a.original else None

    for raiz in a.raices:
        cfg = yaml.safe_load((raiz / 'data.yaml').read_text(encoding='utf-8'))
        nombres = cfg['names']
        nombres = [nombres[i] for i in sorted(nombres)] if isinstance(nombres, dict) else list(nombres)
        if nombres != VIEJAS:
            raise SystemExit(f'{raiz}: las clases no son las 8 esperadas: {nombres}')
        archivos = 0
        for lab in sorted(raiz.glob('labels/*/*.txt')):
            lineas = []
            for ln in lab.read_text().splitlines():
                v = ln.split()
                if v:
                    lineas.append(' '.join([str(MAPA[int(v[0])])] + v[1:]))
            tmp = lab.with_suffix('.txt.nuevo')
            tmp.write_text('\n'.join(lineas) + ('\n' if lineas else ''), encoding='utf-8')
            os.replace(tmp, lab)  # archivo nuevo: no toca el original aunque fuera un enlace duro
            archivos += 1
        for cache in raiz.glob('labels/*.cache'):  # el caché de Ultralytics quedó viejo
            cache.unlink()
        cfg['names'] = {i: n for i, n in enumerate(NUEVAS)}
        (raiz / 'data.yaml').write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding='utf-8')
        print(f'{raiz}: {archivos} etiquetas reescritas, 8 -> 6 clases', flush=True)

    if antes_original is not None:
        despues = histograma(a.original)
        print('\noriginal', a.original, 'intacto:', antes_original == despues, f'(clases 3, 4 y 5 siguen en {antes_original[3]}, {antes_original[4]}, {antes_original[5]})')
        if antes_original != despues:
            raise SystemExit('¡EL ORIGINAL CAMBIÓ!')


if __name__ == '__main__':
    main()
