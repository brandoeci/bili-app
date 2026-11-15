"""Paridad del seguimiento (IDs entre cuadros) entre Ultralytics (ByteTrack) y web/bili/seguimiento.js.

Genera escenarios con semilla: objetos que se mueven, crecen, parpadean, se tapan más de 30 cuadros, se cruzan y aparecen pegados, con
confianzas por encima y por debajo de los umbrales de ByteTrack. Cada cuadro pasa por el BYTETracker de Ultralytics y por la misma lógica
que aplican `on_predict_postprocess_end` y `YoloDetector.track` (caja del filtro en enteros, recortada). Con --detecciones se agregan
cuadros reales (salida de scripts/movil/seguimiento_videos.py). Luego `node scripts/movil/paridad_seguimiento.mjs ARCHIVO` compara.

Uso: python -I scripts/movil/paridad_seguimiento.py --salida seguimiento.json [--escenarios 80] [--semilla 11] [--detecciones dets.json]"""
import argparse
import json
import random
from pathlib import Path

import numpy as np
from ultralytics.engine.results import Boxes
from ultralytics.trackers.byte_tracker import BYTETracker
from ultralytics.utils import YAML, IterableSimpleNamespace
from ultralytics.utils.checks import check_yaml

ALTO, ANCHO = 640, 480


def nuevo_seguidor() -> BYTETracker:
    return BYTETracker(IterableSimpleNamespace(**YAML.load(check_yaml('bytetrack.yaml'))))


def salida_servidor(seguidor: BYTETracker, dets: list[dict], ancho: int, alto: int) -> tuple[list[dict], list[list[float]]]:
    """Lo que devuelve YoloDetector.track para estas detecciones (antes del filtro por clase), y las cajas del filtro sin redondear."""
    datos = np.array([[*d['bbox'], d['conf'], d['cls']] for d in dets], dtype=np.float32).reshape(-1, 6)
    pistas = seguidor.update(Boxes(datos, (alto, ancho)), None)

    def recortar(b):
        x1, y1, x2, y2 = (int(v) for v in b)
        return [max(0, x1), max(0, y1), min(ancho, x2), min(alto, y2)]

    if len(pistas) == 0:
        if any(not t.is_activated for t in seguidor.tracked_stracks):
            return [], []
        return [{'track_id': None, 'cls': int(r[5]), 'conf': float(r[4]), 'bbox': recortar(r[:4].tolist())} for r in datos], []
    return ([{'track_id': int(p[4]), 'cls': int(p[6]), 'conf': float(p[5]), 'bbox': recortar(p[:4].tolist())} for p in pistas],
            [[float(v) for v in p[:4]] for p in pistas])


def escenario(rng: random.Random) -> list[list[dict]]:
    objetos = []
    for _ in range(rng.randint(1, 6)):
        w0, h0 = rng.uniform(10, 180), rng.uniform(20, 420)
        desde = rng.randint(0, 20)
        tapa = rng.randint(desde + 3, desde + 30)
        quieto = rng.random() < 0.3   # un poste con el celular quieto: tras un tapado vuelve donde estaba
        objetos.append({
            'cls': rng.randint(0, 5), 'cx': rng.uniform(0, ANCHO), 'cy': rng.uniform(ALTO * 0.2, ALTO * 1.05), 'w': w0, 'h': h0,
            'vx': 0 if quieto else rng.uniform(-14, 14), 'vy': 0 if quieto else rng.uniform(-6, 18), 'crece': 1 if quieto else rng.uniform(0.97, 1.06),
            'conf': rng.uniform(0.05, 0.95), 'vconf': rng.uniform(-0.02, 0.02), 'desde': desde, 'hasta': rng.randint(desde + 5, 110),
            # tapado de 29 a 32 cuadros: justo en el límite de track_buffer (30), donde una pista quitada aún puede volver
            'tapa': (tapa, tapa + rng.choice([2, 5, 12, 29, 30, 31, 32, 35])) if rng.random() < 0.5 else None,
            'gemelo': rng.random() < 0.15,   # otra detección casi encima (otra clase), como bordillo y escalera en la misma caja
            'salto': rng.randint(desde + 4, desde + 20) if rng.random() < 0.15 else None,   # la cámara gira de golpe
        })
    cuadros = []
    for f in range(rng.randint(30, 120)):
        dets = []
        for o in objetos:
            if not (o['desde'] <= f <= o['hasta']) or rng.random() < 0.07:
                continue
            if o['tapa'] and o['tapa'][0] <= f < o['tapa'][1]:
                continue
            n = f - o['desde']
            w, h = o['w'] * o['crece'] ** n, o['h'] * o['crece'] ** n
            ruido = 0.5 if o['vx'] == 0 else 2
            cx, cy = o['cx'] + o['vx'] * n + rng.gauss(0, ruido), o['cy'] + o['vy'] * n + rng.gauss(0, ruido)
            if o['salto'] and f >= o['salto']:
                cx += 140
            x1, y1, x2, y2 = (min(lim, max(0.0, v)) for v, lim in ((cx - w / 2, ANCHO), (cy - h / 2, ALTO), (cx + w / 2, ANCHO), (cy + h / 2, ALTO)))
            if rng.random() < 0.02:
                y2 = y1   # caja sin alto: ByteTrack la descarta
            conf = min(0.99, max(0.02, o['conf'] + o['vconf'] * n + rng.uniform(-0.08, 0.08)))
            dets.append({'cls': o['cls'], 'conf': conf, 'bbox': [x1, y1, x2, y2]})
            if o['gemelo']:
                dets.append({'cls': (o['cls'] + 1) % 6, 'conf': conf * rng.uniform(0.6, 1.0),
                             'bbox': [x1 + rng.uniform(-3, 3), y1 + rng.uniform(-3, 3), x2 + rng.uniform(-3, 3), y2 + rng.uniform(-3, 3)]})
        rng.shuffle(dets)
        # como llegan del modelo: float32
        cuadros.append([{'cls': d['cls'], 'conf': float(np.float32(d['conf'])), 'bbox': [float(np.float32(v)) for v in d['bbox']]} for d in dets])
    return cuadros


def correr(cuadros: list[list[dict]], ancho: int, alto: int) -> list[dict]:
    seg = nuevo_seguidor()
    pasos = []
    for dets in cuadros:
        esperado, cajas = salida_servidor(seg, dets, ancho, alto)
        pasos.append({'dets': dets, 'esperado': esperado, 'cajas': cajas})
    return pasos


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--salida', type=Path, required=True)
    ap.add_argument('--escenarios', type=int, default=80)
    ap.add_argument('--semilla', type=int, default=11)
    ap.add_argument('--detecciones', type=Path, nargs='*', default=[], help='cuadros reales de seguimiento_videos.py')
    a = ap.parse_args()
    rng = random.Random(a.semilla)
    escenarios = [{'ancho': ANCHO, 'alto': ALTO, 'origen': f'sintetico-{i}', 'pasos': correr(escenario(rng), ANCHO, ALTO)} for i in range(a.escenarios)]
    for archivo in a.detecciones:
        for tramo in json.load(open(archivo, encoding='utf-8'))['tramos']:
            escenarios.append({'ancho': tramo['ancho'], 'alto': tramo['alto'], 'origen': tramo['nombre'],
                               'pasos': correr(tramo['cuadros'], tramo['ancho'], tramo['alto'])})
    json.dump({'escenarios': escenarios}, open(a.salida, 'w', encoding='utf-8'))
    cuadros = sum(len(e['pasos']) for e in escenarios)
    ids = sum(len({d['track_id'] for p in e['pasos'] for d in p['esperado'] if d['track_id'] is not None}) for e in escenarios)
    print(f'{len(escenarios)} escenarios, {cuadros} cuadros, {ids} IDs distintos -> {a.salida}')


if __name__ == '__main__':
    main()
