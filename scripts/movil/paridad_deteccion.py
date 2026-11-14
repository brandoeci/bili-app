"""Prepara la prueba de paridad del detector del celular: el mismo cuadro, el mismo modelo ONNX, ¿da lo mismo en JavaScript que en Python?

Por cada cuadro: letterbox con el LetterBox de Ultralytics, salida cruda de ONNX Runtime (lo que verá el JS) y detecciones de referencia
de Ultralytics (conf 0,35, IoU 0,5, escaleras 0,50, como la app). Luego `node scripts/movil/paridad_deteccion.mjs CARPETA` decodifica la
salida cruda con web/bili/deteccion.js y compara.

Uso: python -I scripts/movil/paridad_deteccion.py --modelo models/onnx/bili-hazards-v6b_640x480.onnx --salida CARPETA --cuadros a.jpg b.jpg ..."""
import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np
import onnxruntime as ort
from ultralytics import YOLO
from ultralytics.data.augment import LetterBox

CONF, IOU, CLASE_CONF = 0.35, 0.5, {'stairs': 0.5}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--modelo', type=Path, required=True)
    ap.add_argument('--salida', type=Path, required=True)
    ap.add_argument('--cuadros', type=Path, nargs='+', required=True)
    a = ap.parse_args()
    a.salida.mkdir(parents=True, exist_ok=True)

    sesion = ort.InferenceSession(str(a.modelo), providers=['CPUExecutionProvider'])
    H, W = sesion.get_inputs()[0].shape[2:]
    ref = YOLO(str(a.modelo), task='detect')
    nombres = None
    casos = []
    for i, p in enumerate(a.cuadros):
        img = cv2.imdecode(np.fromfile(str(p), np.uint8), cv2.IMREAD_COLOR)
        lb = LetterBox((H, W), auto=False, scale_fill=False, scaleup=True, center=True)(image=img)
        x = cv2.cvtColor(lb, cv2.COLOR_BGR2RGB).transpose(2, 0, 1)[None].astype(np.float32) / 255
        crudo = sesion.run(None, {sesion.get_inputs()[0].name: x})[0].astype(np.float32)
        crudo.tofile(str(a.salida / f'{i:03d}.bin'))
        r = ref.predict(lb, imgsz=(H, W), conf=CONF, iou=IOU, device='cpu', verbose=False)[0]
        nombres = r.names
        dets = [{'clase': int(b.cls), 'conf': float(b.conf), 'caja': [float(v) for v in b.xyxy[0].tolist()]} for b in r.boxes
                if float(b.conf) >= CLASE_CONF.get(r.names[int(b.cls)], 0)]
        casos.append({'cuadro': str(p), 'crudo': f'{i:03d}.bin', 'forma': list(crudo.shape), 'origen': [img.shape[1], img.shape[0]], 'referencia': dets})
    clase_conf = {str(k): CLASE_CONF[v] for k, v in nombres.items() if v in CLASE_CONF}
    json.dump({'modelo': str(a.modelo), 'entrada': [H, W], 'nClases': len(nombres), 'conf': CONF, 'iou': IOU, 'claseConf': clase_conf,
               'nombres': nombres, 'casos': casos}, open(a.salida / 'casos.json', 'w'), indent=1)
    print(f'{len(casos)} cuadros -> {a.salida} | detecciones de referencia: {sum(len(c["referencia"]) for c in casos)}')


if __name__ == '__main__':
    sys.exit(main())
