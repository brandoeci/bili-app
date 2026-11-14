"""¿Qué tan seguido acierta el modelo según su confianza? Base para elegir los dos umbrales del motor de decisión (paper, tabla de umbrales):
por encima del ALTO se avisa nombrando la clase; entre el BAJO y el ALTO se pide detenerse sin nombrarla; por debajo del BAJO se calla.

Para cada clase y cada franja de confianza se cuenta qué fracción de las detecciones caen sobre un objeto real de esa clase (IoU >= 0,5).
Uso: python -I scripts/movil/umbrales_abstencion.py --modelo models/bili-hazards-v6b.pt --datos data/bili-dataset-v4 [--split test] [--salida tabla.json]"""
import argparse
import json
from pathlib import Path

import yaml
from ultralytics import YOLO

FRANJAS = [0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.50, 0.60, 0.70, 1.01]


def iou(a, b):
    x1, y1, x2, y2 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    i = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - i
    return i / u if u > 0 else 0.0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--modelo', required=True)
    ap.add_argument('--datos', type=Path, required=True)
    ap.add_argument('--split', default='test')
    ap.add_argument('--salida', type=Path)
    a = ap.parse_args()
    clases = yaml.safe_load(open(a.datos / 'data.yaml', encoding='utf-8'))['names']
    clases = [clases[k] for k in sorted(clases)] if isinstance(clases, dict) else list(clases)
    m = YOLO(a.modelo)
    imgs = sorted(p for p in (a.datos / 'images' / a.split).iterdir() if p.suffix.lower() in {'.jpg', '.jpeg', '.png'})
    # por clase: franja -> [aciertos, total]; y cuántos objetos reales hay
    cuenta = {c: [[0, 0] for _ in FRANJAS[:-1]] for c in clases}
    reales = {c: 0 for c in clases}
    hallados_desde = {c: [0 for _ in FRANJAS[:-1]] for c in clases}   # objetos reales encontrados con conf >= franja
    for i in range(0, len(imgs), 16):
        lote = imgs[i:i + 16]
        for p, r in zip(lote, m.predict([str(x) for x in lote], conf=FRANJAS[0], iou=0.5, imgsz=640, device='cpu', verbose=False)):
            H, W = r.orig_shape
            gt = []
            lab = a.datos / 'labels' / a.split / (p.stem + '.txt')
            for l in (lab.read_text().splitlines() if lab.exists() else []):
                q = l.split()
                if len(q) < 5: continue
                c, cx, cy, w, h = int(q[0]), *map(float, q[1:5])
                gt.append([clases[c], [(cx - w / 2) * W, (cy - h / 2) * H, (cx + w / 2) * W, (cy + h / 2) * H], 0.0])
                reales[clases[c]] += 1
            dets = sorted(((r.names[int(b.cls)], float(b.conf), b.xyxy[0].tolist()) for b in r.boxes), key=lambda d: -d[1])
            for nombre, conf, caja in dets:
                nombre = 'stairs' if nombre.startswith('stairs') else nombre
                if nombre not in cuenta: continue
                k = next(j for j in range(len(FRANJAS) - 1) if FRANJAS[j] <= conf < FRANJAS[j + 1])
                mejor = max((g for g in gt if g[0] == nombre and g[2] == 0.0), key=lambda g: iou(g[1], caja), default=None)
                acierto = mejor is not None and iou(mejor[1], caja) >= 0.5
                if acierto:
                    mejor[2] = conf
                    for j in range(k + 1): hallados_desde[nombre][j] += 1
                cuenta[nombre][k][0] += acierto; cuenta[nombre][k][1] += 1
    tabla = {}
    for c in clases:
        print(f'\n{c} ({reales[c]} reales)')
        print('  franja        detecciones  aciertan  precisión de la franja | recall si se avisa desde aquí')
        filas = []
        for j in range(len(FRANJAS) - 1):
            ok, n = cuenta[c][j]
            rec = hallados_desde[c][j] / max(reales[c], 1)
            filas.append({'desde': FRANJAS[j], 'hasta': min(FRANJAS[j + 1], 1.0), 'n': n, 'aciertos': ok, 'precision': ok / n if n else None, 'recall_desde': rec})
            print(f'  {FRANJAS[j]:.2f}-{min(FRANJAS[j + 1], 1):.2f}  {n:11d}  {ok:8d}  {(ok / n if n else float("nan")):22.2f} | {rec:.2f}')
        tabla[c] = {'reales': reales[c], 'franjas': filas}
    if a.salida:
        json.dump({'modelo': a.modelo, 'split': a.split, 'tabla': tabla}, open(a.salida, 'w'), indent=1)


if __name__ == '__main__':
    main()
