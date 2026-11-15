"""¿Qué se pierde en el celular sin la compensación de movimiento de BoT-SORT? Compara seguidores en tramos reales caminando.

Saca tramos de un video a 8 cuadros/s (el ritmo de la app), los pasa por el detector de peligros una sola vez y da las MISMAS detecciones a:
  - BoT-SORT (lo que usa hoy el servidor: compensa el movimiento de la cámara con flujo óptico de OpenCV),
  - ByteTrack (lo que se puede copiar al navegador: web/bili/seguimiento.js),
  - ningún seguidor (sin IDs).
Mide IDs distintos, duración de las pistas y cuánto hablaría Bili (fusión + alertas con abstención). No hay etiquetas de identidad: menos
IDs y pistas más largas con las mismas detecciones indican menos cortes. Guarda las detecciones para paridad_seguimiento.py.

Uso: python -I scripts/movil/seguimiento_videos.py --modelo models/bili-hazards-v7a.pt --video RUTA.MOV --desde 60 300 540 --segundos 60
       --salida dets.json"""
import argparse
import json
import statistics
import sys
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from ultralytics import YOLO  # noqa: E402
from ultralytics.engine.results import Boxes  # noqa: E402
from ultralytics.trackers.bot_sort import BOTSORT  # noqa: E402
from ultralytics.trackers.byte_tracker import BYTETracker  # noqa: E402
from ultralytics.utils import YAML, IterableSimpleNamespace  # noqa: E402
from ultralytics.utils.checks import check_yaml  # noqa: E402

from app.config import Settings  # noqa: E402
from app.core.alerts import AlertManager  # noqa: E402
from app.core.decision import confianza_minima  # noqa: E402
from app.core.fusion import FusionEngine  # noqa: E402
from app.schemas import Detection  # noqa: E402

FPS = 8
ANCHO = 480


def tramo(video: Path, desde: float, segundos: float) -> list[np.ndarray]:
    cap = cv2.VideoCapture(str(video))
    cap.set(cv2.CAP_PROP_POS_MSEC, desde * 1000)
    cuadros, siguiente = [], desde
    while True:
        ok, img = cap.read()
        if not ok:
            break
        t = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000
        if t >= desde + segundos:
            break
        if t + 1e-6 >= siguiente:
            h, w = img.shape[:2]
            cuadros.append(cv2.resize(img, (ANCHO, round(h * ANCHO / w)), interpolation=cv2.INTER_AREA))
            siguiente += 1 / FPS
    cap.release()
    return cuadros


def seguidor(nombre: str):
    if nombre == 'ninguno':
        return None
    clase = BOTSORT if nombre == 'botsort' else BYTETracker
    return clase(IterableSimpleNamespace(**YAML.load(check_yaml(f'{nombre}.yaml'))))


def con_ids(seg, dets: list[dict], img: np.ndarray) -> list[tuple]:
    """(track_id, label, conf, bbox) como YoloDetector.track."""
    alto, ancho = img.shape[:2]
    recortar = lambda b: (max(0, int(b[0])), max(0, int(b[1])), min(ancho, int(b[2])), min(alto, int(b[3])))  # noqa: E731
    if seg is None:
        return [(None, d['label'], d['conf'], recortar(d['bbox'])) for d in dets]
    datos = np.array([[*d['bbox'], d['conf'], d['cls']] for d in dets], dtype=np.float32).reshape(-1, 6)
    pistas = seg.update(Boxes(datos, (alto, ancho)), img)
    if len(pistas) == 0:
        if any(not t.is_activated for t in seg.tracked_stracks):
            return []
        return [(None, d['label'], d['conf'], recortar(d['bbox'])) for d in dets]
    return [(int(p[4]), dets[int(p[7])]['label'], float(p[5]), recortar(p[:4].tolist())) for p in pistas]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--modelo', required=True)
    ap.add_argument('--video', type=Path, required=True)
    ap.add_argument('--desde', type=float, nargs='+', required=True, help='segundos donde empieza cada tramo')
    ap.add_argument('--segundos', type=float, default=60)
    ap.add_argument('--salida', type=Path, required=True)
    a = ap.parse_args()
    s = Settings(_env_file=None)
    tabla = s.tabla_decision()
    m = YOLO(a.modelo)
    tramos, totales = [], {n: Counter() for n in ('botsort', 'bytetrack', 'ninguno')}
    duraciones = {n: [] for n in totales}
    for desde in a.desde:
        imgs = tramo(a.video, desde, a.segundos)
        if not imgs:
            print(f'tramo {desde}s vacío')
            continue
        cuadros = []
        for i in range(0, len(imgs), 16):
            for r in m.predict(imgs[i:i + 16], conf=confianza_minima(tabla), imgsz=640, device='cpu', verbose=False):
                cuadros.append([{'cls': int(b.cls), 'label': r.names[int(b.cls)], 'conf': float(b.conf), 'bbox': [float(v) for v in b.xyxy[0].tolist()]}
                                for b in r.boxes])
        alto, ancho = imgs[0].shape[:2]
        nombre = f'{a.video.stem}@{desde:g}s'
        tramos.append({'nombre': nombre, 'ancho': ancho, 'alto': alto, 'cuadros': cuadros})
        print(f'\n== {nombre}: {len(imgs)} cuadros ({len(imgs) / FPS:.0f} s), {sum(map(len, cuadros))} detecciones')
        for n in totales:
            seg = seguidor(n)
            fusion = FusionEngine(focal_ratio=s.camera_focal_ratio, proximity=s.proximity_config(), decision=tabla, decidir_conducta=True)
            alertas = AlertManager(cooldown_s=s.alerts_cooldown_s, min_frames=s.alerts_min_frames, max_speech_rate_s=s.alerts_max_speech_rate_s,
                                   reminder_s=s.alerts_reminder_s)
            vistos, c = Counter(), Counter()
            for f, (img, dets) in enumerate(zip(imgs, cuadros)):
                salida = con_ids(seg, dets, img)
                c['detecciones'] += len(dets)
                c['con id'] += sum(x[0] is not None for x in salida)
                for x in salida:
                    if x[0] is not None:
                        vistos[x[0]] += 1
                t = f / FPS
                fus = fusion.update([Detection(track_id=i, label=l, conf=cf, bbox=b) for i, l, cf, b in salida], None, img.shape, now=t)
                for al in alertas.evaluate(fus, now=t):
                    c['deténgase' if al.text.startswith('Deténgase') else 'con clase'] += 1
            c['ids'] = len(vistos)
            c['segundos'] = len(imgs) / FPS
            duraciones[n] += list(vistos.values())
            totales[n].update(c)
            med = statistics.median(vistos.values()) / FPS if vistos else 0
            print(f'  {n:10s} IDs {len(vistos):4d} | mediana de pista {med:4.1f} s | detecciones con ID {c["con id"]}/{c["detecciones"]} | '
                  f'avisos con clase {c["con clase"]}, deténgase {c["deténgase"]}')
    print('\n== total')
    for n, c in totales.items():
        mins = c['segundos'] / 60 or 1
        med = statistics.median(duraciones[n]) / FPS if duraciones[n] else 0
        print(f'  {n:10s} IDs {c["ids"]:4d} | mediana de pista {med:4.1f} s | con ID {c["con id"]}/{c["detecciones"]} | '
              f'con clase {c["con clase"] / mins:4.1f}/min, deténgase {c["deténgase"] / mins:4.1f}/min')
    json.dump({'tramos': tramos}, open(a.salida, 'w', encoding='utf-8'))
    print(f'detecciones -> {a.salida}')


if __name__ == '__main__':
    main()
