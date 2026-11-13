"""Corre un detector sobre una lista de vistas y guarda TODAS las detecciones por encima de --conf en un CSV (no copia imágenes).

Sirve para buscar candidatos (escaleras, alcantarillas, etc.) en la zona reservada de STRIDE. Para reducir el sesgo de un solo
modelo se corre con varios y se unen los CSV: un candidato cuenta si CUALQUIERA de los modelos lo marca.

Uso: python -I scripts/stride/buscar_candidatos.py --modelo models/bili-hazards.pt --vistas CARPETA --lista reservada.txt --salida candidatos_v2.csv [--conf 0.10]
"""
import argparse
import csv
import math
import time
from pathlib import Path

from ultralytics import YOLO


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--modelo', required=True)
    ap.add_argument('--vistas', type=Path, required=True)
    ap.add_argument('--lista', type=Path, required=True)
    ap.add_argument('--salida', type=Path, required=True)
    ap.add_argument('--conf', type=float, default=0.10)
    ap.add_argument('--tanda', type=int, default=16)
    a = ap.parse_args()

    nombres_img = [n for n in a.lista.read_text(encoding='utf-8').splitlines() if n.strip()]
    rutas = [a.vistas / n for n in nombres_img]
    modelo = YOLO(a.modelo)
    t0 = time.time()
    filas, invalidas = 0, 0
    with open(a.salida, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['imagen', 'clase', 'conf', 'cx', 'cy', 'w', 'h'])
        for i in range(0, len(rutas), a.tanda):
            # tandas explícitas: con una lista larga Ultralytics no respeta el batch y se queda sin memoria
            for r in modelo.predict([str(p) for p in rutas[i:i + a.tanda]], conf=a.conf, imgsz=640, verbose=False):
                for c, s, xywhn in zip(r.boxes.cls, r.boxes.conf, r.boxes.xywhn):
                    v = [float(t) for t in xywhn]
                    if not all(math.isfinite(t) for t in v) or not all(0 <= t <= 1 for t in v) or v[2] <= 0 or v[3] <= 0:
                        invalidas += 1
                        continue
                    w.writerow([Path(r.path).name, modelo.names[int(c)], round(float(s), 4)] + [round(t, 5) for t in v])
                    filas += 1
            if (i // a.tanda) % 50 == 0:
                print(f'{min(i + a.tanda, len(rutas))}/{len(rutas)} vistas | {filas} detecciones | {time.time() - t0:.0f} s', flush=True)
    print(f'LISTO: {len(rutas)} vistas, {filas} detecciones, {invalidas} inválidas descartadas, {time.time() - t0:.0f} s')


if __name__ == '__main__':
    main()
