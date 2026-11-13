"""Convierte los huecos (D40) de RDD2022 a formato YOLO, leyendo directo del zip (zip de zips, sin descomprimir en disco).

Toma solo imágenes del conjunto train que tengan al menos una caja D40. La clase queda como 'pothole' (id 0 del proyecto).
Las otras clases de daño (grietas, etc.) no se etiquetan: en esas imágenes cuentan como fondo.
Las imágenes se reducen a 640 px de lado mayor. El nombre conserva el país de origen.

RDD2022 es CC BY 4.0: hay que citar a Arya et al. (2022), https://doi.org/10.6084/m9.figshare.21431547.v1

Uso: python -I scripts/rdd/convertir_rdd2022.py ZIP --salida CARPETA [--paises India,Japan,...]
"""
import argparse
import csv
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

CLASE_HUECO = 0  # 'pothole' en el orden de clases del proyecto
LADO = 640


def cajas_d40(xml_bytes):
    """[(xmin, ymin, xmax, ymax)] de las cajas D40, en píxeles de la imagen original."""
    raiz = ET.fromstring(xml_bytes)
    out = []
    for o in raiz.iter('object'):
        if (o.findtext('name') or '').strip() != 'D40':
            continue
        b = o.find('bndbox')
        try:
            out.append(tuple(float(b.findtext(k)) for k in ('xmin', 'ymin', 'xmax', 'ymax')))
        except (TypeError, ValueError, AttributeError):
            continue
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('zip')
    ap.add_argument('--salida', required=True)
    ap.add_argument('--paises', default='India,Japan,Czech,China_MotorBike,United_States')
    a = ap.parse_args()
    paises = set(a.paises.split(','))
    out = Path(a.salida)
    (out / 'images').mkdir(parents=True, exist_ok=True)
    (out / 'labels').mkdir(parents=True, exist_ok=True)

    cuenta = Counter()
    cajas_total = Counter()
    descartes = Counter()
    z = zipfile.ZipFile(a.zip)
    with open(out / 'resumen.csv', 'w', newline='', encoding='utf-8') as fcsv:
        w = csv.writer(fcsv)
        w.writerow(['imagen', 'pais', 'cajas'])
        for info in z.infolist():
            pais = Path(info.filename).stem
            if pais not in paises:
                continue
            with z.open(info) as f, zipfile.ZipFile(f) as zi:
                nombres = {i.filename: i for i in zi.infolist() if not i.is_dir()}
                for n in sorted(nombres):
                    if not (n.lower().endswith('.xml') and '/train/' in n and '/annotations/' in n):
                        continue
                    cajas = cajas_d40(zi.read(n))
                    if not cajas:
                        continue
                    base = Path(n).stem
                    ruta_img = next((k for k in (n.replace('/annotations/xmls/', '/images/').rsplit('.', 1)[0] + e for e in ('.jpg', '.JPG', '.jpeg')) if k in nombres), None)
                    if ruta_img is None:
                        descartes['sin imagen'] += 1
                        continue
                    img = cv2.imdecode(np.frombuffer(zi.read(ruta_img), np.uint8), cv2.IMREAD_COLOR)
                    if img is None:
                        descartes['imagen ilegible'] += 1
                        continue
                    h, wd = img.shape[:2]
                    lineas = []
                    for x1, y1, x2, y2 in cajas:
                        x1, x2 = max(0.0, min(x1, x2)), min(float(wd), max(x1, x2))
                        y1, y2 = max(0.0, min(y1, y2)), min(float(h), max(y1, y2))
                        if x2 - x1 < 2 or y2 - y1 < 2:
                            descartes['caja degenerada'] += 1
                            continue
                        lineas.append(f'{CLASE_HUECO} {(x1 + x2) / 2 / wd:.6f} {(y1 + y2) / 2 / h:.6f} {(x2 - x1) / wd:.6f} {(y2 - y1) / h:.6f}')
                    if not lineas:
                        descartes['sin cajas validas'] += 1
                        continue
                    s = LADO / max(h, wd)
                    if s < 1:
                        img = cv2.resize(img, (round(wd * s), round(h * s)), interpolation=cv2.INTER_AREA)
                    nombre = f'rdd2022_{pais}_{base}'
                    cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, 90])[1].tofile(str(out / 'images' / f'{nombre}.jpg'))
                    (out / 'labels' / f'{nombre}.txt').write_text('\n'.join(lineas) + '\n', encoding='utf-8')
                    w.writerow([f'{nombre}.jpg', pais, len(lineas)])
                    cuenta[pais] += 1
                    cajas_total[pais] += len(lineas)
            print('listo', pais, cuenta[pais], 'imagenes', cajas_total[pais], 'cajas', flush=True)
    (out / 'classes.txt').write_text('pothole\n', encoding='utf-8')
    print('TOTAL imagenes:', sum(cuenta.values()), '| cajas:', sum(cajas_total.values()), '| descartes:', dict(descartes))


if __name__ == '__main__':
    main()
