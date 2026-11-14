"""Arma el dataset v6 = v5 + postes revisados a ojo (cajas que propuso Grounding DINO, revisadas por dos personas).

Reglas (ver v6_logica.py): una vista con caja MAL / en conflicto / marcada con varios postes queda fuera; una con postes reales es positiva
(las cajas dudosas y los candidatos que nadie revisó se TAPAN con relleno para que un poste sin etiqueta no se aprenda como fondo); una con
solo falsos es negativa si ningún modelo ve en ella otra clase. Solo vistas de la zona ENTRENABLE; val y test del v5 no se tocan y se
descarta cualquier vista que sea (casi) copia -también volteada- de una de val/test.

Uso: python -I scripts/stride/armar_v6.py --v5 data/bili-dataset-v5 --out data/bili-dataset-v6 --reparto CARPETA_postes-reparto \
       --dino dino_bogota.json dino_bogota2.json --modelos modelos_en_vistas.json --vistas CARPETA_stride-vistas \
       --zonas CARPETA_stride-zonas --escaleras CARPETA_escaleras-reparto/veredictos_globales.csv"""
import argparse
import csv
import json
import os
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / 'dataset'))
from limpiar_v4 import _hh, hashes  # noqa: E402
from v5_logica import linea_yolo  # noqa: E402
from v6_logica import cajas_extra, iou_xyxy, plan_vista, unir_veredictos  # noqa: E402
from zonas import zona  # noqa: E402

CLASES = ['pothole', 'manhole', 'curb', 'stairs', 'pole', 'obstacle']
ID_POLE = CLASES.index('pole')
CONF_MODELO = 0.5          # un modelo que ve algo con esta confianza cuenta como "hay algo ahí"


def enlazar(src: Path, dst: Path) -> None:
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def leer(path: Path) -> dict[int, str]:
    return {int(r['global']): r['veredicto'] for r in csv.DictReader(open(path, encoding='utf-8-sig'))}


def tapar(img: np.ndarray, cajas) -> np.ndarray:
    """Borra del dibujo las cajas dudosas (reconstruye el fondo con el vecindario) para que no queden como poste sin etiqueta."""
    h, w = img.shape[:2]
    mask = np.zeros((h, w), np.uint8)
    for x1, y1, x2, y2 in cajas:
        cv2.rectangle(mask, (max(0, int(x1) - 2), max(0, int(y1) - 2)), (min(w - 1, int(x2) + 2), min(h - 1, int(y2) + 2)), 255, -1)
    return cv2.inpaint(img, mask, 3, cv2.INPAINT_TELEA)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--v5', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--reparto', type=Path, required=True)
    ap.add_argument('--dino', type=Path, nargs='+', required=True)
    ap.add_argument('--modelos', type=Path, required=True)
    ap.add_argument('--vistas', type=Path, required=True)
    ap.add_argument('--zonas', type=Path, required=True)
    ap.add_argument('--escaleras', type=Path, required=True, help='veredictos de escaleras: esas vistas ya están en el v5 y no se repiten')
    ap.add_argument('--repetir', type=int, default=3)
    ap.add_argument('--limpiar-bogota', type=Path, help='JSON de DINO sobre las imágenes bogota-* del v5: se tapan los postes que nadie etiquetó')
    ap.add_argument('--modelos-bogota', type=Path, help='JSON de v2/v4 sobre esas mismas imágenes (postes con confianza alta)')
    ap.add_argument('--solo-resumen', action='store_true', help='calcula y muestra el plan sin copiar nada')
    a = ap.parse_args()
    if a.out.exists() and not a.solo_resumen:
        sys.exit('La salida ya existe: no la piso. Bórrela a mano si quiere rehacerla.')

    maestro = {int(r['global']): r for r in csv.DictReader(open(a.reparto / 'MAPA_MAESTRO_no_enviar.csv', encoding='utf-8-sig'))}
    mi_filas = list(csv.DictReader(open(a.reparto / 'veredictos_mi.csv', encoding='utf-8-sig')))
    ver = unir_veredictos({int(r['global']): r['veredicto'] for r in mi_filas}, leer(a.reparto / 'veredictos_diego.csv'))
    varios = {maestro[int(r['global'])]['vista'] for r in mi_filas if r['postes_en_la_vista_si_hay_mas_de_uno'] not in ('', '0')}
    dino = {}
    for f in a.dino:
        dino.update(json.load(open(f)))
    modelos = json.load(open(a.modelos))
    entrenable = {l.strip() for l in open(a.zonas / 'entrenable.txt', encoding='utf-8') if l.strip()}
    en_v5 = {r['vista'] for r in csv.DictReader(open(a.escaleras, encoding='utf-8-sig'))}

    por_vista: dict[str, list] = defaultdict(list)
    for g, v in ver.items():
        m = maestro[g]
        if m['origen'] != 'train':
            continue                       # las vistas de la zona reservada son el EXAMEN: nunca se entrenan
        assert m['vista'] in entrenable and zona(m['vista']) == 'entrenable', f'{m["vista"]} no es de la zona entrenable'
        por_vista[m['vista']].append(([float(m[k]) for k in ('x1', 'y1', 'x2', 'y2')], v))

    planes, motivos = {}, Counter()
    for vista, revisadas in por_vista.items():
        if vista in en_v5:
            motivos['ya está en el v5 (escaleras)'] += 1
            continue
        cajas_rev = [b for b, _ in revisadas]
        extras = cajas_extra(dino.get(vista, {}).get('cajas', []), cajas_rev)
        # postes que ven los modelos (v2/v5) con confianza alta y nadie revisó
        mod_postes = [d[2:6] + [d[1]] for d in modelos.get(vista, []) if d[0] == 'pole' and d[1] >= CONF_MODELO]
        for c in cajas_extra(mod_postes, cajas_rev + extras, minimo=CONF_MODELO, forma=1.0):
            extras.append(c)
        p = plan_vista(revisadas, extras, marcada_varios=vista in varios)
        otras = {d[0] for d in modelos.get(vista, []) if d[0] != 'pole' and d[1] >= CONF_MODELO}
        if p['accion'] in ('negativo', 'positivo') and otras:
            # Otra clase (bordillo, hueco...) que un modelo ve y nadie etiquetó: quedaría como fondo. El bordillo ya es la clase más débil.
            tipo = 'negativa' if p['accion'] == 'negativo' else 'positiva'
            p = {'accion': 'fuera', 'motivo': f'{tipo} con otra clase ({", ".join(sorted(otras))})', 'positivas': [], 'tapar': []}
        p['otras'] = sorted(otras)
        planes[vista] = p
        motivos[p['accion'] if p['accion'] != 'fuera' else f'fuera: {p["motivo"]}'] += 1

    pos = [v for v, p in planes.items() if p['accion'] == 'positivo']
    neg = [v for v, p in planes.items() if p['accion'] == 'negativo']
    print('plan:', dict(motivos))
    print(f'positivas {len(pos)} ({sum(len(planes[v]["positivas"]) for v in pos)} postes) | negativas {len(neg)} | '
          f'con algo tapado: {sum(1 for v in pos + neg if planes[v]["tapar"])} | positivas que además tienen otra clase sin etiquetar: '
          f'{sum(1 for v in pos if planes[v]["otras"])}')
    if a.solo_resumen:
        return

    # --- comprobación contra copias de val/test (también volteadas)
    ref = []
    for split in ('val', 'test'):
        ps, h, hm, ok = hashes(a.v5 / 'images' / split)
        ref.append(h[ok])
    ref = np.concatenate(ref)
    copias = set()
    for vista in pos + neg:
        img = cv2.imdecode(np.fromfile(str(a.vistas / vista), np.uint8), cv2.IMREAD_REDUCED_GRAYSCALE_4)
        if img is None:
            continue
        h, hm = np.uint64(_hh(img)), np.uint64(_hh(cv2.flip(img, 1)))
        if min(int(np.bitwise_count(ref ^ h).min()), int(np.bitwise_count(ref ^ hm).min())) <= 8:
            copias.add(vista)
    if copias:
        print('descartadas por ser copia de val/test:', len(copias))

    for split in ('train', 'val', 'test'):
        for kind in ('images', 'labels'):
            (a.out / kind / split).mkdir(parents=True)
            for f in (a.v5 / kind / split).iterdir():
                enlazar(f, a.out / kind / split / f.name)
    shutil.copy2(a.v5 / 'data.yaml', a.out / 'data.yaml')

    if a.limpiar_bogota:
        # Las vistas de Bogotá que entraron al v5 (escaleras positivas y negativas) tienen postes sin etiquetar: el v5 aprendió que un poste
        # de Bogotá es fondo (recall de postes 0,23 -> 0,07 en el examen). Aquí se tapan esos postes, sin tocar las cajas de escalera.
        dino_b = json.load(open(a.limpiar_bogota))
        mod_b = json.load(open(a.modelos_bogota)) if a.modelos_bogota else {}
        lim = Counter()
        for nombre, d in sorted(dino_b.items()):
            base = nombre[:-len('-r0.jpg')]
            W, H = d['wh']
            escaleras = []
            for linea in (a.v5 / 'labels' / 'train' / f'{base}-r0.txt').read_text().splitlines():
                if linea.strip():
                    cx, cy, w, h = (float(x) for x in linea.split()[1:5])
                    escaleras.append([(cx - w / 2) * W, (cy - h / 2) * H, (cx + w / 2) * W, (cy + h / 2) * H])
            extras = cajas_extra(d['cajas'], escaleras, cubierta_igual=0.2)
            mp = [x[2:6] + [x[1]] for x in mod_b.get(nombre, []) if x[0] == 'pole' and x[1] >= CONF_MODELO]
            extras += cajas_extra(mp, escaleras + extras, minimo=CONF_MODELO, forma=1.0, cubierta_igual=0.2)
            if not extras:
                lim['sin postes que tapar'] += 1
                continue
            img = cv2.imdecode(np.fromfile(str(a.v5 / 'images' / 'train' / nombre), np.uint8), cv2.IMREAD_COLOR)
            datos = cv2.imencode('.jpg', tapar(img, extras), [cv2.IMWRITE_JPEG_QUALITY, 95])[1]
            for k in range(10):
                destino = a.out / 'images' / 'train' / f'{base}-r{k}.jpg'
                if destino.exists():
                    destino.unlink()          # solo el nombre del v6: el archivo del v5 y la vista original no se tocan
                    datos.tofile(str(destino))
            lim['vistas con postes tapados'] += 1
            lim['cajas tapadas'] += len(extras)
        print('limpieza de las vistas de Bogotá del v5:', dict(lim))

    cuenta = Counter()
    with open(a.out / 'vistas_v6.csv', 'w', newline='', encoding='utf-8-sig') as fcsv:
        w = csv.writer(fcsv)
        w.writerow(['vista', 'accion', 'motivo', 'postes', 'tapadas', 'otras clases vistas por el modelo'])
        for i, (vista, p) in enumerate(sorted(planes.items())):
            w.writerow([vista, p['accion'] if vista not in copias else 'fuera', p['motivo'] or ('copia de val/test' if vista in copias else ''),
                        len(p['positivas']), len(p['tapar']), ' '.join(p['otras'])])
            if p['accion'] == 'fuera' or vista in copias:
                continue
            img = cv2.imdecode(np.fromfile(str(a.vistas / vista), np.uint8), cv2.IMREAD_COLOR)
            h, wd = img.shape[:2]
            if p['tapar']:
                img = tapar(img, p['tapar'])
            tipo = 'pos' if p['accion'] == 'positivo' else 'neg'
            lineas = [linea_yolo(ID_POLE, ((b[0] + b[2]) / 2 / wd, (b[1] + b[3]) / 2 / h, (b[2] - b[0]) / wd, (b[3] - b[1]) / h)) for b in p['positivas']]
            for k in range(a.repetir):
                nombre = f'poste-{tipo}-{i:04d}-r{k}'
                destino = a.out / 'images' / 'train' / f'{nombre}.jpg'
                if k == 0:
                    cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, 95])[1].tofile(str(destino))
                else:
                    enlazar(a.out / 'images' / 'train' / f'poste-{tipo}-{i:04d}-r0.jpg', destino)
                (a.out / 'labels' / 'train' / f'{nombre}.txt').write_text('\n'.join(lineas) + ('\n' if lineas else ''), encoding='utf-8')
            cuenta[tipo] += 1
            cuenta['postes'] += len(lineas)

    print(f'\nv6 en {a.out}')
    print(f'  vistas positivas {cuenta["pos"]} ({cuenta["postes"]} postes) | negativas {cuenta["neg"]} | cada imagen x{a.repetir} | detalle en vistas_v6.csv')


if __name__ == '__main__':
    main()
