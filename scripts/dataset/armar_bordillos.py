"""Arma una ronda de bordillos: dataset base (v6b) + imágenes de los videos con los bordillos DIBUJADOS A MANO.

Reglas:
  - Solo hay etiqueta de bordillo (clase 2): lo que la persona dibujó. Las cajas de tamaño casi cero (un clic sin arrastrar) se descartan.
  - Una imagen sin cajas es "sin bordillo cercano" (la persona no vio ninguno): se agrega como negativa.
  - Todo lo demás que se detecte (postes por DINO; el resto de clases por el modelo) se TAPA con relleno, para que no se aprenda como fondo.
    Lo que cae sobre un bordillo dibujado no se tapa.
  - Cada imagen se repite --repetir veces (son pocas frente a ~28 mil). val y test del dataset base no se tocan.

Uso: python -I scripts/dataset/armar_bordillos.py --base data/bili-dataset-v6b --out data/bili-dataset-v7a --paquetes CARPETA_bordillos-reparto \
       --zips mi_etiquetas.zip diego_etiquetas.zip --dino dino_bordillos.json --modelo modelo_bordillos_ronda.json"""
import argparse
import json
import os
import shutil
import sys
import zipfile
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent / 'stride'))
from armar_v6 import tapar  # noqa: E402
from limpiar_v4 import _hh, hashes  # noqa: E402
from v5_logica import linea_yolo  # noqa: E402
from v6_logica import cajas_extra  # noqa: E402

ID_CURB = 2
MIN_LADO = 0.004          # fracción de la imagen: por debajo es un clic sin arrastrar


def cajas_px(lineas: list[str], w: int, h: int, minimo: float = MIN_LADO) -> list[list[float]]:
    """Líneas YOLO ('clase cx cy w h' normalizadas) -> cajas [x1, y1, x2, y2] en píxeles, recortadas a la imagen. Descarta las diminutas."""
    out = []
    for linea in lineas:
        p = linea.split()
        if len(p) < 5:
            continue
        cx, cy, bw, bh = (float(v) for v in p[1:5])
        if bw < minimo or bh < minimo:
            continue
        x1, y1, x2, y2 = (cx - bw / 2) * w, (cy - bh / 2) * h, (cx + bw / 2) * w, (cy + bh / 2) * h
        out.append([max(0.0, x1), max(0.0, y1), min(float(w), x2), min(float(h), y2)])
    return out


def lineas_curb(cajas: list[list[float]], w: int, h: int) -> list[str]:
    return [linea_yolo(ID_CURB, ((c[0] + c[2]) / 2 / w, (c[1] + c[3]) / 2 / h, (c[2] - c[0]) / w, (c[3] - c[1]) / h)) for c in cajas]


def enlazar(src: Path, dst: Path) -> None:
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--paquetes', type=Path, required=True, help='carpeta con para-mi/imagenes y para-diego/imagenes')
    ap.add_argument('--zips', type=Path, nargs='+', required=True, help='zips de etiquetas YOLO exportados (con una sola clase)')
    ap.add_argument('--dino', type=Path, required=True)
    ap.add_argument('--modelo', type=Path, required=True)
    ap.add_argument('--repetir', type=int, default=8)
    a = ap.parse_args()
    if a.out.exists():
        sys.exit('La salida ya existe: no la piso. Bórrela a mano si quiere rehacerla.')

    etiquetas = {}
    for z in a.zips:
        with zipfile.ZipFile(z) as zf:
            for n in zf.namelist():
                if n.endswith('.txt'):
                    etiquetas[Path(n).stem] = zf.read(n).decode().splitlines()
    dino, modelo = json.load(open(a.dino)), json.load(open(a.modelo))
    imagenes = sorted(list((a.paquetes / 'para-mi' / 'imagenes').glob('*.jpg')) + list((a.paquetes / 'para-diego' / 'imagenes').glob('*.jpg')))
    desconocidas = set(etiquetas) - {p.stem for p in imagenes}
    if desconocidas:
        sys.exit(f'Etiquetas sin imagen: {sorted(desconocidas)[:5]}')

    # --- copia de la base y comprobación contra copias de val/test
    ref = np.concatenate([hashes(a.base / 'images' / s)[1][hashes(a.base / 'images' / s)[3]] for s in ('val', 'test')])
    for split in ('train', 'val', 'test'):
        for kind in ('images', 'labels'):
            (a.out / kind / split).mkdir(parents=True)
            for f in (a.base / kind / split).iterdir():
                enlazar(f, a.out / kind / split / f.name)
    shutil.copy2(a.base / 'data.yaml', a.out / 'data.yaml')

    cuenta = Counter()
    for i, p in enumerate(imagenes):
        img = cv2.imdecode(np.fromfile(str(p), np.uint8), cv2.IMREAD_COLOR)
        h, w = img.shape[:2]
        gris = cv2.imdecode(np.fromfile(str(p), np.uint8), cv2.IMREAD_REDUCED_GRAYSCALE_4)
        hh, hm = np.uint64(_hh(gris)), np.uint64(_hh(cv2.flip(gris, 1)))
        if min(int(np.bitwise_count(ref ^ hh).min()), int(np.bitwise_count(ref ^ hm).min())) <= 8:
            cuenta['descartada: copia de val/test'] += 1
            continue
        dibujadas = cajas_px(etiquetas.get(p.stem, []), w, h)
        # candidatos a tapar: nunca los que caen sobre un bordillo dibujado
        extras = cajas_extra(dino[p.name]['cajas'], dibujadas, cubierta_igual=0.2)
        prop = [c[2:6] + [c[1]] for c in modelo[p.name]['cajas'] if c[0] != 'curb']
        extras += cajas_extra(prop, dibujadas + extras, minimo=0.15, forma=1.0, cubierta_igual=0.2)
        if extras:
            img = tapar(img, extras)
            cuenta['imágenes con algo tapado'] += 1
        lineas = lineas_curb(dibujadas, w, h)
        tipo = 'pos' if lineas else 'neg'
        datos = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, 95])[1]
        for k in range(a.repetir):
            nombre = f'bordillo-{tipo}-{i:03d}-r{k}'
            destino = a.out / 'images' / 'train' / f'{nombre}.jpg'
            if k == 0:
                datos.tofile(str(destino))
            else:
                enlazar(a.out / 'images' / 'train' / f'bordillo-{tipo}-{i:03d}-r0.jpg', destino)
            (a.out / 'labels' / 'train' / f'{nombre}.txt').write_text('\n'.join(lineas) + ('\n' if lineas else ''), encoding='utf-8')
        cuenta[tipo] += 1
        cuenta['cajas de bordillo'] += len(lineas)
        cuenta['cajas tapadas'] += len(extras)
        cuenta['cajas diminutas descartadas'] += len(etiquetas.get(p.stem, [])) - len(dibujadas)

    print(f'\nronda en {a.out}')
    for k, v in sorted(cuenta.items()):
        print(f'  {k}: {v}')
    print(f'  cada imagen x{a.repetir} -> {(cuenta["pos"] + cuenta["neg"]) * a.repetir} imágenes nuevas, {cuenta["cajas de bordillo"] * a.repetir} bordillos nuevos')


if __name__ == '__main__':
    main()
