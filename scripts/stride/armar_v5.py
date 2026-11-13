"""Arma el dataset v5 = v4 + escaleras revisadas en calles de Bogotá (positivos con caja, y negativos difíciles).

Qué entra (ver v5_logica.py):
  - REAL con una sola caja (o cajas de los dos modelos que coinciden): positivo, clase 'stairs'.
  - REAL con cajas que no coinciden: AMBIGUA -> fuera, y se lista en ambiguas.csv para mirarla.
  - FALSO sin otras clases detectadas: negativo (etiqueta vacía). FALSO con otras clases (postes...): fuera, se lista en mixtas.csv.
  - DUDOSO y MAL: fuera.
Val y test del v4 NO se tocan (el examen sigue siendo el mismo, para poder comparar). Solo vistas de la zona ENTRENABLE de STRIDE.
Se descarta cualquier vista nueva que sea (casi) copia -también volteada- de una de val/test.
Las imágenes nuevas se repiten --repetir veces en el train: son pocas frente a ~25 mil y, sin repetirlas, casi no pesarían.

Uso: python -I scripts/stride/armar_v5.py --v4 data/bili-dataset-v4 --out data/bili-dataset-v5 --veredictos veredictos_globales.csv \
       --cajas .../cajas_modelos.json --zonas CARPETA_stride-zonas --banco CARPETA_stride-vistas --escogidas CARPETA_stride-escogidas/entrenable"""
import argparse
import csv
import json
import os
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / 'dataset'))
from limpiar_v4 import distancias, hashes  # noqa: E402
from v5_logica import agrupar, clasificar_real, linea_yolo, negativo_limpio  # noqa: E402
from zonas import zona  # noqa: E402

CLASES = ['pothole', 'manhole', 'curb', 'stairs', 'pole', 'obstacle']
ID_STAIRS = CLASES.index('stairs')


def enlazar(src: Path, dst: Path) -> None:
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def otras_clases(zonas: Path) -> dict[str, dict[str, float]]:
    """vista -> {clase: mayor confianza} de las clases que NO son escalera, juntando los 4 CSV de candidatos (v2/v4, banco/escogidas)."""
    d: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for nombre in ('ent_candidatos_v2.csv', 'ent_candidatos_v4.csv', 'esc_candidatos_v2.csv', 'esc_candidatos_v4.csv'):
        for r in csv.DictReader(open(zonas / nombre, encoding='utf-8')):
            if not r['clase'].startswith('stairs'):
                d[r['imagen']][r['clase']] = max(d[r['imagen']][r['clase']], float(r['conf']))
    return d


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--v4', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--veredictos', type=Path, required=True)
    ap.add_argument('--cajas', type=Path, required=True)
    ap.add_argument('--zonas', type=Path, required=True)
    ap.add_argument('--banco', type=Path, required=True)
    ap.add_argument('--escogidas', type=Path, required=True)
    ap.add_argument('--repetir', type=int, default=3)
    a = ap.parse_args()
    if a.out.exists():
        sys.exit('La salida ya existe: no la piso. Bórrela a mano si quiere rehacerla.')
    carpeta = {'banco': a.banco, 'escogidas': a.escogidas}

    cajas = json.load(open(a.cajas, encoding='utf-8'))
    otras = otras_clases(a.zonas)
    positivos, negativos, ambiguas, mixtas, fuera = [], [], [], [], Counter()
    for r in csv.DictReader(open(a.veredictos, encoding='utf-8-sig')):
        g, origen, vista, v = int(r['global']), r['origen'], r['vista'], r['veredicto']
        if zona(vista) != 'entrenable':
            fuera['zona reservada o franja (NO se entrena)'] += 1
            continue
        if v in ('dudoso', 'mal'):
            fuera[v] += 1
        elif v == 'real':
            info = cajas[f'{g:04d}']
            tipo, grupos = clasificar_real(agrupar(info['v2'], info['v4']))
            (positivos if tipo == 'positivo' else ambiguas).append((g, origen, vista, grupos))
        elif v == 'falso':
            if negativo_limpio(otras.get(vista, {})):
                negativos.append((g, origen, vista))
            else:
                mixtas.append((g, origen, vista, dict(otras[vista])))

    # --- copia de la base (enlaces duros: no duplica espacio) y comprobación de copias contra val/test
    nuevas = [(p[2], p[1]) for p in positivos] + [(n[2], n[1]) for n in negativos]
    tmp_hash = {}
    for split in ('val', 'test'):
        ps, h, hm, ok = hashes(a.v4 / 'images' / split)
        tmp_hash[split] = (h[ok], )
    ref = np.concatenate([tmp_hash['val'][0], tmp_hash['test'][0]])
    import cv2
    from limpiar_v4 import _hh  # noqa: E402
    copias = set()
    for vista, origen in nuevas:
        img = cv2.imdecode(np.fromfile(str(carpeta[origen] / vista), np.uint8), cv2.IMREAD_REDUCED_GRAYSCALE_4)
        if img is None:
            continue
        h, hm = np.uint64(_hh(img)), np.uint64(_hh(cv2.flip(img, 1)))
        if min(int(np.bitwise_count(ref ^ h).min()), int(np.bitwise_count(ref ^ hm).min())) <= 8:
            copias.add(vista)
    if copias:
        print('descartadas por ser copia de val/test:', len(copias))

    for split in ('train', 'val', 'test'):
        for kind in ('images', 'labels'):
            (a.out / kind / split).mkdir(parents=True)
            for f in (a.v4 / kind / split).iterdir():
                enlazar(f, a.out / kind / split / f.name)
    shutil.copy2(a.v4 / 'data.yaml', a.out / 'data.yaml')

    cuenta = Counter()
    for tipo, lista in (('pos', positivos), ('neg', negativos)):
        for item in lista:
            g, origen, vista = item[0], item[1], item[2]
            if vista in copias:
                continue
            lineas = [linea_yolo(ID_STAIRS, item[3][0]['caja'])] if tipo == 'pos' else []
            for k in range(a.repetir):
                nombre = f'bogota-{tipo}-{g:04d}-r{k}'
                enlazar(carpeta[origen] / vista, a.out / 'images' / 'train' / f'{nombre}.jpg') if k else shutil.copy2(carpeta[origen] / vista, a.out / 'images' / 'train' / f'{nombre}.jpg')
                (a.out / 'labels' / 'train' / f'{nombre}.txt').write_text('\n'.join(lineas) + ('\n' if lineas else ''), encoding='utf-8')
            cuenta[tipo] += 1

    with open(a.out / 'ambiguas.csv', 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f); w.writerow(['global', 'origen', 'vista', 'cajas (cx cy w h | modelos)'])
        for g, o, v, grupos in ambiguas:
            w.writerow([g, o, v, ' || '.join(f'{x["caja"][0]:.2f} {x["caja"][1]:.2f} {x["caja"][2]:.2f} {x["caja"][3]:.2f} | {"+".join(x["modelos"])}' for x in grupos)])
    with open(a.out / 'mixtas.csv', 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f); w.writerow(['global', 'origen', 'vista', 'otras clases detectadas'])
        for g, o, v, d in mixtas:
            w.writerow([g, o, v, ', '.join(f'{c} {s:.2f}' for c, s in sorted(d.items(), key=lambda x: -x[1]))])

    print(f'\nv5 en {a.out}')
    print(f'  positivos (escalera real con caja): {cuenta["pos"]}  | negativos limpios: {cuenta["neg"]}  | cada imagen repetida x{a.repetir}')
    print(f'  fuera: ambiguas {len(ambiguas)} (ver ambiguas.csv) | falsas con otras clases {len(mixtas)} (ver mixtas.csv) | {dict(fuera)}')
    print(f'  imágenes nuevas en train: {cuenta["pos"] * a.repetir + cuenta["neg"] * a.repetir}')


if __name__ == '__main__':
    main()
