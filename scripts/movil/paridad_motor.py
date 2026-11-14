"""Paridad del motor de decisión (fusión + zonas + prioridad + conducta + alertas) entre Python y JavaScript.

Genera escenarios sintéticos con semilla: objetos que se acercan, se alejan y cambian de lado, con y sin track_id, con confianzas dentro y fuera
de la banda de incertidumbre, a ~8 cuadros/s con variaciones. Pasa cada escenario por FusionEngine y AlertManager de Python (con la config del
servidor) y guarda entradas y salidas. Luego `node scripts/movil/paridad_motor.mjs ARCHIVO` repite todo con web/bili/ y compara.

Uso: python -I scripts/movil/paridad_motor.py --salida motor.json [--escenarios 60] [--semilla 7]"""
import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.config import Settings  # noqa: E402
from app.core.alerts import AlertManager  # noqa: E402
from app.core.fusion import FusionEngine  # noqa: E402
from app.schemas import Detection  # noqa: E402

CLASES = ['person', 'car', 'bicycle', 'dog', 'chair', 'laptop', 'kite', 'pothole', 'curb', 'stairs', 'stairs_down', 'pole', 'obstacle', 'manhole']
ALTO, ANCHO = 640, 480


def escenario(rng: random.Random) -> list[dict]:
    objetos = []
    for k in range(rng.randint(1, 4)):
        w0, h0 = rng.uniform(15, 160), rng.uniform(30, 400)
        objetos.append({
            'label': rng.choice(CLASES), 'track': None if rng.random() < 0.2 else 100 + k,
            'cx': rng.uniform(20, ANCHO - 20), 'base': rng.uniform(ALTO * 0.35, ALTO + 10), 'w': w0, 'h': h0,
            'vx': rng.uniform(-25, 25), 'vbase': rng.uniform(-10, 45), 'crece': rng.uniform(0.98, 1.08),
            'conf': rng.uniform(0.2, 0.95), 'vconf': rng.uniform(-0.03, 0.04), 'desde': rng.randint(0, 10), 'hasta': rng.randint(15, 60),
        })
    pasos, t = [], 0.0
    for f in range(rng.randint(20, 70)):
        t += rng.choice([0.125, 0.125, 0.11, 0.14, 0.5, 1.2])   # a veces el celular se atrasa
        crudas = []
        for o in objetos:
            if not (o['desde'] <= f <= o['hasta']) or rng.random() < 0.08:   # parpadeos
                continue
            n = f - o['desde']
            w, h = o['w'] * o['crece'] ** n, o['h'] * o['crece'] ** n
            cx, base = o['cx'] + o['vx'] * n * 0.3, o['base'] + o['vbase'] * n * 0.3
            x1, y1, x2, y2 = (int(round(v)) for v in (cx - w / 2, base - h, cx + w / 2, base))
            x1, y1, x2, y2 = max(0, x1), max(0, y1), min(ANCHO, x2), min(ALTO, y2)
            if x2 - x1 < 2 or y2 - y1 < 2:
                continue
            conf = round(min(0.99, max(0.21, o['conf'] + o['vconf'] * n + rng.uniform(-0.05, 0.05))), 4)
            crudas.append({'track_id': o['track'], 'label': o['label'], 'conf': conf, 'bbox': [x1, y1, x2, y2]})
        pasos.append({'t': round(t, 4), 'crudas': crudas})
    return pasos


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--salida', type=Path, required=True)
    ap.add_argument('--escenarios', type=int, default=60)
    ap.add_argument('--semilla', type=int, default=7)
    a = ap.parse_args()
    s = Settings(_env_file=None)
    cfg_alertas = {'cooldown': s.alerts_cooldown_s, 'minFrames': s.alerts_min_frames, 'maxHabla': s.alerts_max_speech_rate_s, 'recordatorio': s.alerts_reminder_s}
    rng = random.Random(a.semilla)
    salida, n_al, n_inc = [], 0, 0
    for _ in range(a.escenarios):
        fusion = FusionEngine(focal_ratio=s.camera_focal_ratio, proximity=s.proximity_config(), decision=s.tabla_decision(), decidir_conducta=True)
        alertas = AlertManager(cooldown_s=s.alerts_cooldown_s, min_frames=s.alerts_min_frames, max_speech_rate_s=s.alerts_max_speech_rate_s,
                               reminder_s=s.alerts_reminder_s)
        pasos = escenario(rng)
        for p in pasos:
            fus = fusion.update([Detection(**c) for c in p['crudas']], None, (ALTO, ANCHO, 3), now=p['t'])
            al = alertas.evaluate(fus, now=p['t'])
            p['fusion'] = [{k: getattr(d, k) for k in ('track_id', 'direction', 'distance_m', 'approach_speed_mps', 'ttc_s', 'priority', 'zone', 'conducta')} for d in fus]
            p['alertas'] = [{'priority': x.priority, 'text': x.text, 'track_id': x.track_id} for x in al]
            n_al += len(al); n_inc += sum(x.text.startswith('Deténgase') for x in al)
        salida.append(pasos)
    json.dump({'alto': ALTO, 'ancho': ANCHO, 'focal': s.camera_focal_ratio, 'alertas': cfg_alertas, 'escenarios': salida}, open(a.salida, 'w', encoding='utf-8'), ensure_ascii=False)
    print(f'{len(salida)} escenarios, {sum(len(e) for e in salida)} cuadros, {n_al} alertas ({n_inc} de incertidumbre) -> {a.salida}')


if __name__ == '__main__':
    main()
