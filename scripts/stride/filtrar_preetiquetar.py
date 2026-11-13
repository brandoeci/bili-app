"""Filtra las vistas de STRIDE y las preetiqueta con el detector propio (bili-hazards).

Para cada vista: corre el modelo; si no detecta nada, la descarta. Las que sí, se copian con su archivo de etiquetas
en formato YOLO (clase cx cy w h, normalizado), listas para subir a Roboflow y CORREGIR a mano.
Para que no domine una sola clase, se queda como máximo con --max-por-clase imágenes por clase (las de mayor confianza).

Uso:
  python -I scripts/stride/filtrar_preetiquetar.py --vistas CARPETA --salida CARPETA [--modelo models/bili-hazards.pt]
                                                   [--conf 0.30] [--max-por-clase 150] [--limite N]
Ojo: las cajas son SUGERENCIAS del propio modelo. Hay que revisarlas; lo que el modelo no conoce no aparece.
"""
import argparse
import csv
import math
import random
import shutil
from collections import Counter, defaultdict
from pathlib import Path

from ultralytics import YOLO


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--vistas', required=True)
    ap.add_argument('--salida', required=True)
    ap.add_argument('--modelo', default='models/bili-hazards.pt')
    ap.add_argument('--conf', type=float, default=0.30)
    ap.add_argument('--max-por-clase', type=int, default=150)
    ap.add_argument('--limite', type=int, default=0, help='procesar solo las primeras N vistas (prueba)')
    ap.add_argument('--cada', type=int, default=1, help='tomar 1 vista de cada N (lotes: --cada 8 --desde 0, luego --desde 1, ...)')
    ap.add_argument('--desde', type=int, default=0, help='con --cada N, cuál de los N lotes procesar (0 a N-1)')
    ap.add_argument('--techo', type=float, default=0, help='descartar vistas con alguna detección >= este valor (para buscar solo las dudosas; usar con --conf bajo)')
    ap.add_argument('--tanda', type=int, default=16, help='imágenes por tanda (bajar si falta memoria)')
    a = ap.parse_args()
    import torch
    usa_gpu = torch.cuda.is_available()
    print('GPU:', torch.cuda.get_device_name(0) if usa_gpu else 'no (procesador)', flush=True)

    imgs = sorted(Path(a.vistas).glob('*.jpg'))
    # Las 4 vistas de un panorama quedan seguidas: sin mezclar, "1 de cada 8" tomaría siempre el mismo ángulo.
    # Con semilla fija el reparto es el mismo en cada corrida, así los lotes no se repiten entre sí.
    random.Random(2026).shuffle(imgs)
    imgs = imgs[a.desde::a.cada]
    print(f'Lote: {len(imgs)} vistas (1 de cada {a.cada}, desde {a.desde})', flush=True)
    if a.limite:
        imgs = imgs[: a.limite]
    modelo = YOLO(a.modelo)
    nombres = modelo.names

    por_imagen = {}  # ruta -> lista de (clase, conf, cx, cy, w, h)
    total = invalidas = ya_vistas = 0
    def resultados():
        # Tandas explícitas: con una lista larga, `batch=` no se respeta y el modelo intenta procesar todo junto (sin memoria).
        for i in range(0, len(imgs), a.tanda):
            yield from modelo.predict([str(p) for p in imgs[i:i + a.tanda]], conf=a.conf, imgsz=640, verbose=False)  # sin half=True: en GTX 16xx el FP16 da cajas NaN

    for r in resultados():
        total += 1
        todas = [(int(c), float(s), *map(float, xywhn)) for c, s, xywhn in zip(r.boxes.cls, r.boxes.conf, r.boxes.xywhn)]
        # Una caja con coordenadas no numéricas o fuera de la imagen es un fallo del cálculo, no una detección
        dets = [d for d in todas if all(math.isfinite(v) for v in d[1:]) and 0 <= d[2] <= 1 and 0 <= d[3] <= 1 and d[4] > 0 and d[5] > 0]
        invalidas += len(todas) - len(dets)
        if a.techo and any(d[1] >= a.techo for d in dets):
            ya_vistas += 1  # el modelo ya la vio con seguridad en la selección normal: aquí solo interesan las dudosas
            dets = []
        if dets:
            por_imagen[Path(r.path)] = dets
        if total % 100 == 0:
            print(f'{total}/{len(imgs)} vistas revisadas, {len(por_imagen)} con algo', flush=True)

    # Selección balanceada: por cada clase, las imágenes donde esa clase sale con más confianza
    elegidas = set()
    por_clase = defaultdict(list)
    for ruta, dets in por_imagen.items():
        for c in {d[0] for d in dets}:
            por_clase[c].append((max(d[1] for d in dets if d[0] == c), ruta))
    for c, lista in por_clase.items():
        lista.sort(key=lambda t: -t[0])
        elegidas.update(ruta for _, ruta in lista[: a.max_por_clase])

    out = Path(a.salida)
    (out / 'images').mkdir(parents=True, exist_ok=True)
    (out / 'labels').mkdir(parents=True, exist_ok=True)
    cuenta = Counter()
    with open(out / 'resumen.csv', 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['imagen', 'clase', 'confianza'])
        for ruta in sorted(elegidas):
            shutil.copy2(ruta, out / 'images' / ruta.name)
            lineas = []
            for c, s, cx, cy, bw, bh in por_imagen[ruta]:
                lineas.append(f'{c} {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}')
                w.writerow([ruta.name, nombres[c], round(s, 3)])
                cuenta[nombres[c]] += 1
            (out / 'labels' / (ruta.stem + '.txt')).write_text('\n'.join(lineas) + '\n', encoding='utf-8')
    (out / 'classes.txt').write_text('\n'.join(nombres[i] for i in sorted(nombres)) + '\n', encoding='utf-8')

    print(f'Cajas inválidas descartadas (NaN o fuera de la imagen): {invalidas}')
    if a.techo:
        print(f'Vistas omitidas por tener una detección segura (>= {a.techo}): {ya_vistas}')
    print(f'Vistas revisadas: {total} | con alguna detección: {len(por_imagen)} | elegidas: {len(elegidas)}')
    print('Cajas por clase en las elegidas:', dict(cuenta))


if __name__ == '__main__':
    main()
