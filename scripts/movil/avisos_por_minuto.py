"""¿Cuánto hablaría Bili caminando? Pasa los cuadros de un video (1 por segundo) por el detector de peligros, la fusión y las alertas, y cuenta
avisos por minuto, con y sin el motor de decisión (abstención). Mide la molestia, no la exactitud: no hay etiquetas.

Límites: un cuadro por segundo (la app procesa ~8): sin seguimiento entre cuadros (cada objeto se recuerda por clase y lado), y sin el detector
de COCO (personas, carros), así que la cuenta real sería mayor.
Uso: python -I scripts/movil/avisos_por_minuto.py --modelo models/bili-hazards-v7a.pt --video data/video-0763 [--video ...]"""
import argparse
import csv
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from ultralytics import YOLO  # noqa: E402

from app.config import Settings  # noqa: E402
from app.core.alerts import AlertManager  # noqa: E402
from app.core.decision import confianza_minima  # noqa: E402
from app.core.fusion import FusionEngine  # noqa: E402
from app.schemas import Detection  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--modelo', required=True)
    ap.add_argument('--video', type=Path, nargs='+', required=True)
    a = ap.parse_args()
    s = Settings(_env_file=None)
    tabla = s.tabla_decision()
    m = YOLO(a.modelo)
    for carpeta in a.video:
        filas = [r for r in csv.DictReader(open(carpeta / 'cuadros.csv', encoding='utf-8-sig')) if not r['descartado_por']]
        crudas = {}
        for i in range(0, len(filas), 16):
            lote = filas[i:i + 16]
            for r, res in zip(lote, m.predict([str(carpeta / 'cuadros' / x['cuadro']) for x in lote], conf=confianza_minima(tabla), imgsz=640, device='cpu', verbose=False)):
                crudas[r['cuadro']] = (res.orig_shape, [(res.names[int(b.cls)], float(b.conf), [int(v) for v in b.xyxy[0].tolist()]) for b in res.boxes])
        minutos = len(filas) / 60
        print(f'\n== {carpeta.name}: {len(filas)} cuadros (~{minutos:.1f} min)')
        for nombre, abst in (('sin abstención (umbral 0,35; escaleras 0,50)', False), ('con abstención', True)):
            fusion = FusionEngine(focal_ratio=s.camera_focal_ratio, proximity=s.proximity_config(), decision=tabla, decidir_conducta=abst)
            alertas = AlertManager(cooldown_s=s.alerts_cooldown_s, min_frames=s.alerts_min_frames, max_speech_rate_s=s.alerts_max_speech_rate_s,
                                   reminder_s=s.alerts_reminder_s)
            c = Counter()
            for r in filas:
                (h, w), dets = crudas[r['cuadro']]
                if not abst:   # comportamiento de antes: el detector filtra a 0,35 y las escaleras a 0,50
                    dets = [d for d in dets if d[1] >= s.hazard_conf and d[1] >= s.hazard_class_conf.get(d[0], 0)]
                fus = fusion.update([Detection(track_id=None, label=l, conf=cf, bbox=b) for l, cf, b in dets], None, (h, w, 3), now=float(r['segundo']))
                for al in alertas.evaluate(fus, now=float(r['segundo'])):
                    c['deténgase' if al.text.startswith('Deténgase') else 'avisos con clase'] += 1
            total = sum(c.values())
            print(f'  {nombre:45s} total {total:4d} ({total / minutos:4.1f}/min) | con clase {c["avisos con clase"]} | deténgase {c["deténgase"]} ({c["deténgase"] / minutos:.1f}/min)')


if __name__ == '__main__':
    main()
