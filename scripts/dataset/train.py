"""Afina YOLO con el dataset unificado de peligros de Bili.

    python scripts/dataset/train.py                       # usa GPU si hay, si no CPU (lento)
    python scripts/dataset/train.py --epochs 80 --imgsz 640 --base models/yolo26s.pt

En CPU un entrenamiento real tarda días: use una GPU (Colab/Kaggle gratis sirven). Se sube la carpeta
data/bili-dataset y este script, y se descarga runs/bili-hazards/weights/best.pt.

Resultado: models/bili-hazards.pt. Es un detector SEPARADO del de COCO (personas, carros...): si se
afinara el de COCO solo con estas clases olvidaría las demás.
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

_here = Path(__file__).resolve()
# En el repo vive en scripts/dataset/; suelto (Colab) la raíz es su propia carpeta.
ROOT = _here.parents[2] if len(_here.parents) > 2 and (_here.parents[2] / 'app').is_dir() else _here.parent


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', type=Path, default=ROOT / 'data' / 'bili-dataset' / 'data.yaml')
    ap.add_argument('--base', default=str(ROOT / 'models' / 'yolo26s.pt'))
    ap.add_argument('--epochs', type=int, default=60)
    ap.add_argument('--imgsz', type=int, default=640)
    ap.add_argument('--batch', type=int, default=16)
    ap.add_argument('--device', default=None, help='0 para la primera GPU, cpu, mps')
    ap.add_argument('--project', type=Path, default=ROOT / 'runs', help='dónde guardar; en Colab, una carpeta de Drive')
    args = ap.parse_args()

    if not args.data.exists():
        raise SystemExit(f'Falta {args.data}. Primero: python scripts/dataset/prepare_dataset.py ...')

    from ultralytics import YOLO

    model = YOLO(args.base)
    model.train(
        data=str(args.data), epochs=args.epochs, imgsz=args.imgsz, batch=args.batch, device=args.device,
        project=str(args.project), name='bili-hazards', exist_ok=True,
        patience=15,          # corta si no mejora
        fliplr=0.5, flipud=0.0,  # el suelo nunca va al revés; el espejo horizontal sí es válido
        mosaic=1.0, degrees=0.0,
    )
    metrics = model.val(data=str(args.data), split='test')
    print('\nmAP50-95 en test:', round(float(metrics.box.map), 3), '· mAP50:', round(float(metrics.box.map50), 3))
    print('Por clase en test (solo las que tienen ejemplos): mAP50-95 · mAP50 · recall')
    # box.maps trae un valor por TODAS las clases; las que no tienen ejemplos salen con el promedio global (falso).
    for i, ci in enumerate(metrics.box.ap_class_index):
        name = metrics.names[int(ci)]
        print(f'  {name:<12} {metrics.box.all_ap[i].mean():.3f} · {metrics.box.ap50[i]:.3f} · {metrics.box.r[i]:.3f}')
    absent = [n for k, n in metrics.names.items() if k not in set(int(c) for c in metrics.box.ap_class_index)]
    if absent:
        print('  Sin ejemplos en test (no evaluadas):', ', '.join(absent))

    best = args.project / 'bili-hazards' / 'weights' / 'best.pt'
    if best.exists():
        dest = ROOT / 'models' / 'bili-hazards.pt'
        dest.parent.mkdir(exist_ok=True)
        shutil.copy2(best, dest)
        print(f'\nModelo guardado en {dest}')


if __name__ == '__main__':
    main()
