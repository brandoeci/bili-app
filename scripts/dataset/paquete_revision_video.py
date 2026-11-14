"""Paquetes de revisión de los cuadros del video: una imagen por cuadro con TODAS las cajas candidatas numeradas (todas las clases), repartidas
entre dos revisores (más unos cuadros comunes a los dos para medir cuánto coinciden).

Cada revisor responde, por número de caja, R (real), F (falso), D (dudoso) o MAL (el objeto existe pero la caja está mal), y por cuadro lo que FALTA
(objetos visibles sin caja), porque lo que no tiene caja se aprendería como fondo.

Uso: python -I scripts/dataset/paquete_revision_video.py --video data/video-0763 --modelo modelo_video.json --dino dino_video.json --salida CARPETA"""
import argparse
import csv
import json
import random
import sys
import zipfile
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from candidatos_video import unir_candidatos  # noqa: E402

COLOR = {'pole': (0, 200, 255), 'curb': (255, 120, 0), 'pothole': (0, 0, 255), 'stairs': (0, 255, 0), 'obstacle': (255, 0, 255), 'manhole': (200, 200, 0)}
NOMBRE = {'pole': 'poste', 'curb': 'bordillo', 'pothole': 'hueco', 'stairs': 'escalera', 'obstacle': 'obstaculo', 'manhole': 'tapa'}

LEEME = """Hay {n_cuadros} cuadros (imagenes/001.jpg, 002.jpg...) de un video caminando. En cada uno hay cajas de colores con un NUMERO y el tipo que propone el
modelo: poste (amarillo), bordillo (azul), hueco (rojo), escalera (verde), obstaculo (magenta), tapa de alcantarilla (cian).
Los numeros de las cajas siguen de un cuadro al siguiente; arriba a la izquierda cada cuadro dice F001, F002...

1) PARA CADA CAJA diga si es:
   R   = la caja esta sobre un objeto de ESE tipo y lo cubre razonablemente.
   F   = ahi NO hay un objeto de ese tipo (aunque haya otra cosa).
   D   = no estoy seguro, o esta muy lejos o borroso.
   MAL = SI hay un objeto de ese tipo, pero la caja esta cortada, muy chica o corrida.
2) PARA CADA CUADRO diga que FALTA: objetos de estos tipos que se ven en el cuadro y NO tienen caja.
   Letras: p = poste, b = bordillo, h = hueco, e = escalera, o = obstaculo, t = tapa de alcantarilla.
   Solo cuente lo que se ve claro. Un bordillo que se ve largo en el borde del anden cuenta una vez.

Mande los numeros asi, como siempre:
  Real: ...
  Falso: ...
  Dudoso: ...
  Mal: ...
  Faltan: 12 b, 15 b p, 40 h        (numero de cuadro, F012 = 12, y las letras de lo que falta)
No hace falta listar los cuadros donde no falta nada.
"""


def dibujar(img: np.ndarray, cajas: list[dict], primer_numero: int, cuadro_local: int) -> np.ndarray:
    out = img.copy()
    for k, c in enumerate(cajas):
        x1, y1, x2, y2 = (int(v) for v in c['caja'])
        col = COLOR[c['clase']]
        cv2.rectangle(out, (x1, y1), (x2, y2), col, 3)
        txt = f'{primer_numero + k} {NOMBRE[c["clase"]]}'
        (tw, th), _ = cv2.getTextSize(txt, cv2.FONT_HERSHEY_SIMPLEX, 0.8, 2)
        ty = max(th + 6, y1)
        cv2.rectangle(out, (x1, ty - th - 6), (x1 + tw + 6, ty + 2), (0, 0, 0), -1)
        cv2.putText(out, txt, (x1 + 3, ty - 3), cv2.FONT_HERSHEY_SIMPLEX, 0.8, col, 2)
    cv2.rectangle(out, (0, 0), (110, 40), (0, 0, 0), -1)
    cv2.putText(out, f'F{cuadro_local:03d}', (6, 30), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--video', type=Path, required=True)
    ap.add_argument('--modelo', type=Path, required=True)
    ap.add_argument('--dino', type=Path, required=True)
    ap.add_argument('--salida', type=Path, required=True)
    ap.add_argument('--comunes', type=int, default=20)
    ap.add_argument('--semilla', type=int, default=7)
    ap.add_argument('--prefijo', default='video')
    a = ap.parse_args()
    if a.salida.exists():
        sys.exit('La salida ya existe: no la piso. Bórrela a mano si quiere rehacerla.')

    modelo, dino = json.load(open(a.modelo)), json.load(open(a.dino))
    filas = [r for r in csv.DictReader(open(a.video / 'cuadros.csv', encoding='utf-8-sig')) if not r['descartado_por'] and r['tramo'] in ('train', 'examen')]
    cand = {r['cuadro']: unir_candidatos(modelo[r['cuadro']]['cajas'], dino[r['cuadro']]['cajas']) for r in filas}

    rng = random.Random(a.semilla)
    orden = [r['cuadro'] for r in filas]
    rng.shuffle(orden)
    comunes = orden[:a.comunes]
    resto = orden[a.comunes:]
    reparto = {0: comunes + resto[0::2], 1: comunes + resto[1::2]}       # 0 = Diego, 1 = yo; los comunes van primero en las dos listas
    info = {r['cuadro']: r for r in filas}
    nombres = {0: 'para-diego', 1: 'para-mi'}
    mapa, glob = [], 0
    for k in (0, 1):
        base = a.salida / nombres[k]
        (base / 'imagenes').mkdir(parents=True)
        num = 1
        indice = []
        for n, cuadro in enumerate(reparto[k], 1):
            img = cv2.imdecode(np.fromfile(str(a.video / 'cuadros' / cuadro), np.uint8), cv2.IMREAD_COLOR)
            cajas = sorted(cand[cuadro], key=lambda c: (c['caja'][0], c['caja'][1]))
            cv2.imencode('.jpg', dibujar(img, cajas, num, n), [cv2.IMWRITE_JPEG_QUALITY, 85])[1].tofile(str(base / 'imagenes' / f'{n:03d}.jpg'))
            indice.append([n, num, num + len(cajas) - 1 if cajas else ''])
            for c in cajas:
                glob += 1
                mapa.append([glob, cuadro, info[cuadro]['segundo'], info[cuadro]['tramo'], c['clase'], c['conf'], c['fuente'], *[round(v, 1) for v in c['caja']],
                             'diego' if k == 0 else 'yo', n, num])
                num += 1
        with open(base / 'sus_respuestas.csv', 'w', newline='', encoding='utf-8-sig') as f:
            w = csv.writer(f)
            w.writerow(['numero_de_caja', 'veredicto (R, F, D, MAL)', 'nota'])
            w.writerows([[i, '', ''] for i in range(1, num)])
        with open(base / 'faltan.csv', 'w', newline='', encoding='utf-8-sig') as f:
            w = csv.writer(f)
            w.writerow(['cuadro (F001 = 1)', 'falta (p b h e o t)', 'nota'])
        with open(base / 'indice.csv', 'w', newline='', encoding='utf-8-sig') as f:
            w = csv.writer(f)
            w.writerow(['cuadro', 'primera_caja', 'ultima_caja (vacio si no tiene)'])
            w.writerows(indice)
        (base / 'LEEME.txt').write_text(LEEME.format(n_cuadros=len(reparto[k])), encoding='utf-8')
        z = a.salida / f'{a.prefijo}-{nombres[k]}.zip'
        with zipfile.ZipFile(z, 'w', zipfile.ZIP_STORED) as zf:
            for p in sorted(base.rglob('*')):
                if p.is_file():
                    zf.write(p, f'{a.prefijo}-{nombres[k]}/' + p.relative_to(base).as_posix())
        print(f'{nombres[k]}: {len(reparto[k])} cuadros, {num - 1} cajas, zip {z.stat().st_size / 1e6:.0f} MB')
    with open(a.salida / 'MAPA_MAESTRO_no_enviar.csv', 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['global', 'cuadro', 'segundo', 'tramo', 'clase', 'conf', 'fuente', 'x1', 'y1', 'x2', 'y2', 'revisor', 'cuadro_local', 'caja_local'])
        w.writerows(mapa)
    print(f'cajas únicas: {glob} | comunes: {len(comunes)} cuadros')


if __name__ == '__main__':
    main()
