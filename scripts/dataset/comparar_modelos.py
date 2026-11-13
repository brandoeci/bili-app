"""Compara detectores con el mismo examen y el umbral real de la app: precisión y recall por clase (IoU >= 0.5) y falsas alarmas por imagen.

Sirve para comparar modelos con distinto número de clases: los nombres se llevan a las del examen (el v2 tenía stairs_down,
stairs_up y stairs; el examen v4 tiene una sola 'stairs'), así que las tres del v2 cuentan como 'stairs'.

Uso: python -I scripts/dataset/comparar_modelos.py --modelo models/bili-hazards.pt --datos data/bili-dataset-v4 [--split test]
                                                   [--conf 0.35] [--imgsz 640] [--etiqueta v2] [--salida resultado.json]
"""
import argparse
import json
from collections import defaultdict
from pathlib import Path

import yaml
from ultralytics import YOLO

IMG = {'.jpg', '.jpeg', '.png', '.bmp', '.webp'}


def a_clase_del_examen(nombre: str, clases: list[str]) -> str | None:
    """Lleva el nombre de una clase del modelo a una del examen. stairs_up, stairs_down y stairs cuentan como stairs."""
    if nombre in clases:
        return nombre
    if nombre.startswith('stairs') and 'stairs' in clases:
        return 'stairs'
    return None


def iou(a, b):
    x1, y1, x2, y2 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def xyxy(cx, cy, w, h):
    return (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)


def emparejar(gt: list, pred: list, umbral_iou: float = 0.5):
    """Empareja cajas del examen (gt) con predicciones de UNA clase en UNA imagen. pred = [(conf, caja)]. Devuelve (tp, fp, fn)."""
    usadas = set()
    tp = 0
    for conf, caja in sorted(pred, key=lambda p: -p[0]):
        mejor, j_mejor = 0.0, None
        for j, g in enumerate(gt):
            if j in usadas:
                continue
            v = iou(caja, g)
            if v > mejor:
                mejor, j_mejor = v, j
        if j_mejor is not None and mejor >= umbral_iou:
            usadas.add(j_mejor)
            tp += 1
    return tp, len(pred) - tp, len(gt) - tp


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--modelo', required=True)
    ap.add_argument('--datos', type=Path, required=True)
    ap.add_argument('--split', default='test')
    ap.add_argument('--conf', type=float, default=0.35)
    ap.add_argument('--imgsz', type=int, default=640)
    ap.add_argument('--tanda', type=int, default=16)
    ap.add_argument('--etiqueta', default='')
    ap.add_argument('--salida', type=Path)
    a = ap.parse_args()

    cfg = yaml.safe_load((a.datos / 'data.yaml').read_text(encoding='utf-8'))
    nombres = cfg['names']
    clases = [nombres[i] for i in sorted(nombres)] if isinstance(nombres, dict) else list(nombres)
    imgs = sorted(p for p in (a.datos / 'images' / a.split).iterdir() if p.suffix.lower() in IMG)
    modelo = YOLO(a.modelo)
    mapa = {i: a_clase_del_examen(n, clases) for i, n in modelo.names.items()}
    sin_mapa = [modelo.names[i] for i, c in mapa.items() if c is None]

    tp, fp, fn = defaultdict(int), defaultdict(int), defaultdict(int)
    gt_total = defaultdict(int)
    imgs_con_gt = defaultdict(int)          # imágenes que SÍ tienen la clase
    imgs_alarma_sin_gt = defaultdict(int)   # imágenes que NO la tienen y el modelo la marcó (falsa alarma "de imagen")
    imgs_sin_gt = defaultdict(int)
    for i in range(0, len(imgs), a.tanda):
        lote = imgs[i:i + a.tanda]
        for p, r in zip(lote, modelo.predict([str(x) for x in lote], conf=a.conf, imgsz=a.imgsz, verbose=False)):
            gt = defaultdict(list)
            lab = a.datos / 'labels' / a.split / (p.stem + '.txt')
            if lab.exists():
                for ln in lab.read_text().splitlines():
                    v = ln.split()
                    if len(v) == 5:
                        gt[clases[int(v[0])]].append(xyxy(*[float(t) for t in v[1:]]))
            pred = defaultdict(list)
            for c, s, b in zip(r.boxes.cls, r.boxes.conf, r.boxes.xywhn):
                cl = mapa.get(int(c))
                if cl is not None:
                    pred[cl].append((float(s), xyxy(*[float(t) for t in b])))
            for cl in clases:
                t_, f_, n_ = emparejar(gt[cl], pred[cl])
                tp[cl] += t_; fp[cl] += f_; fn[cl] += n_
                gt_total[cl] += len(gt[cl])
                if gt[cl]:
                    imgs_con_gt[cl] += 1
                else:
                    imgs_sin_gt[cl] += 1
                    imgs_alarma_sin_gt[cl] += 1 if pred[cl] else 0

    etiqueta = a.etiqueta or Path(a.modelo).stem
    print(f'\n{etiqueta} | {a.split}: {len(imgs)} imágenes | conf >= {a.conf} | imgsz {a.imgsz} | IoU >= 0.5')
    if sin_mapa:
        print('  clases del modelo que no existen en el examen (se ignoran):', sin_mapa)
    print(f'  {"clase":12s} {"cajas":>6s} {"aciertos":>9s} {"falsas":>7s} {"se escapan":>11s} | {"precisión":>9s} {"recall":>7s} | imágenes sin la clase donde igual avisó')
    res = {}
    for cl in clases:
        prec = tp[cl] / (tp[cl] + fp[cl]) if tp[cl] + fp[cl] else float('nan')
        rec = tp[cl] / gt_total[cl] if gt_total[cl] else float('nan')
        fa = imgs_alarma_sin_gt[cl] / imgs_sin_gt[cl] if imgs_sin_gt[cl] else float('nan')
        res[cl] = {'cajas': gt_total[cl], 'tp': tp[cl], 'fp': fp[cl], 'fn': fn[cl], 'precision': prec, 'recall': rec, 'falsa_alarma_por_imagen': fa}
        print(f'  {cl:12s} {gt_total[cl]:6d} {tp[cl]:9d} {fp[cl]:7d} {fn[cl]:11d} | {prec:9.2f} {rec:7.2f} | {imgs_alarma_sin_gt[cl]:4d} de {imgs_sin_gt[cl]:4d} ({100 * fa:.1f} %)')
    if a.salida:
        a.salida.write_text(json.dumps({'etiqueta': etiqueta, 'conf': a.conf, 'imgsz': a.imgsz, 'clases': res}, indent=1), encoding='utf-8')


if __name__ == '__main__':
    main()
