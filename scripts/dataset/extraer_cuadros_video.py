"""Saca de un video caminado un cuadro por segundo (el más nítido de cada segundo) y los separa por TRAMOS de tiempo en train / buffer / examen.

Cuadros vecinos se parecen mucho: repartirlos al azar entre entrenamiento y examen filtraría el examen. Por eso el examen son tramos enteros del
video, y alrededor de cada uno se descarta un margen (buffer). No pone etiquetas: solo prepara los cuadros y un CSV con tiempo, nitidez y tramo.

Uso: python -I scripts/dataset/extraer_cuadros_video.py --video IMG_0763.MOV --salida data/video-0763 \
       [--examen 150:195 400:445 650:695] [--margen 10] [--ancho 720]"""
import argparse
import csv
import sys
from pathlib import Path

import cv2
import numpy as np


def tramo(t: float, examen: list[tuple[float, float]], margen: float) -> str:
    """'examen' si t cae dentro de un tramo de examen, 'buffer' si está a menos de `margen` segundos de uno, 'train' en otro caso."""
    for a, b in examen:
        if a <= t < b:
            return 'examen'
    for a, b in examen:
        if a - margen <= t < a or b <= t < b + margen:
            return 'buffer'
    return 'train'


# Umbrales calibrados mirando IMG_0763.MOV (iPhone, 1080x1920): la nitidez va de ~100 a ~11 000 (mediana ~5 300) y la fracción de dedo sobre el
# borde inferior de ~0 a 0,21. Con otro celular o video conviene revisar `descartados/` y ajustar.
UMBRAL_BORROSO = 500.0
UMBRAL_DEDO = 0.06
UMBRAL_OSCURO = 30.0


def fraccion_dedo(img: np.ndarray) -> float:
    """Fracción del 30 % inferior de la imagen que es piel lisa (un dedo sobre el lente). Un suelo liso no cuenta: no tiene color de piel."""
    g = cv2.resize(img, (240, int(240 * img.shape[0] / img.shape[1])))
    h = g.shape[0]
    hsv = cv2.cvtColor(g, cv2.COLOR_BGR2HSV)
    gris = cv2.cvtColor(g, cv2.COLOR_BGR2GRAY)
    piel = ((hsv[..., 0] <= 18) | (hsv[..., 0] >= 172)) & (hsv[..., 1] >= 45) & (hsv[..., 1] <= 190) & (hsv[..., 2] >= 110)
    liso = cv2.blur(cv2.Laplacian(gris, cv2.CV_32F) ** 2, (7, 7)) < 4.0
    return float((piel & liso)[int(h * 0.70):, :].mean())


def motivo_descarte(nitidez: float, brillo: float, dedo: float, umbral_borroso: float = UMBRAL_BORROSO) -> str:
    """El umbral de nitidez NO es igual entre celulares: con otra cámara (más compresión, concreto liso, escaleras de cerca) la nitidez medida baja
    sin que haya desenfoque. Con el video de un Android descartó escaleras y bordillos perfectamente nítidos: ahí se usa --umbral-borroso 0."""
    return 'oscuro' if brillo < UMBRAL_OSCURO else 'dedo en el lente' if dedo > UMBRAL_DEDO else 'borroso' if nitidez < umbral_borroso else ''


def metricas(img: np.ndarray) -> tuple[float, float, float]:
    """(nitidez, brillo, fracción de dedo abajo)."""
    g = cv2.cvtColor(cv2.resize(img, (360, int(360 * img.shape[0] / img.shape[1]))), cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(g, cv2.CV_64F).var()), float(g.mean()), fraccion_dedo(img)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--video', type=Path, required=True)
    ap.add_argument('--salida', type=Path, required=True)
    ap.add_argument('--examen', nargs='*', default=[], help='tramos de examen en segundos, p. ej. 150:195 400:445')
    ap.add_argument('--margen', type=float, default=10.0)
    ap.add_argument('--ancho', type=int, default=720)
    ap.add_argument('--muestras', type=int, default=10, help='cuadros que se comparan por segundo para escoger el más nítido')
    ap.add_argument('--umbral-borroso', type=float, default=UMBRAL_BORROSO, help='nitidez mínima; 0 desactiva el filtro (ver motivo_descarte)')
    a = ap.parse_args()
    if a.salida.exists():
        sys.exit('La salida ya existe: no la piso. Bórrela a mano si quiere rehacerla.')
    examen = [tuple(float(x) for x in e.split(':')) for e in a.examen]
    (a.salida / 'cuadros').mkdir(parents=True)
    (a.salida / 'descartados').mkdir()

    cap = cv2.VideoCapture(str(a.video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    por_seg = max(1, round(fps))
    paso = max(1, por_seg // a.muestras)
    filas, i, seg = [], 0, 0
    mejor = None
    while True:
        ok = cap.grab()
        if not ok:
            break
        if i % paso == 0:
            ok, img = cap.retrieve()
            if ok:
                n, b, p = metricas(img)
                if mejor is None or n > mejor[0]:
                    mejor = (n, b, p, img.copy(), i)
        i += 1
        if i % por_seg == 0:        # cierra el segundo
            if mejor is not None:
                n, b, p, img, idx = mejor
                h = round(img.shape[0] * a.ancho / img.shape[1])
                img = cv2.resize(img, (a.ancho, h), interpolation=cv2.INTER_AREA)
                motivo = motivo_descarte(n, b, p, a.umbral_borroso)
                nombre = f'{a.video.stem}_{seg:04d}s.jpg'
                carpeta = 'descartados' if motivo else 'cuadros'
                cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, 92])[1].tofile(str(a.salida / carpeta / nombre))
                filas.append([nombre, seg, idx, round(n, 1), round(b, 1), round(p, 3), motivo, tramo(seg, examen, a.margen)])
            seg += 1
            mejor = None
        if i % 6000 == 0:
            print(f'{i}/{total} cuadros', flush=True)

    with open(a.salida / 'cuadros.csv', 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['cuadro', 'segundo', 'indice_en_video', 'nitidez', 'brillo', 'fraccion_dedo', 'descartado_por', 'tramo'])
        w.writerows(filas)
    buenos = [r for r in filas if not r[6]]
    print(f'segundos: {len(filas)} | buenos: {len(buenos)} | descartados: {len(filas) - len(buenos)} '
          f'({sorted({r[6] for r in filas if r[6]})})')
    for t in ('train', 'buffer', 'examen'):
        print(f'  {t}: {sum(1 for r in buenos if r[7] == t)} cuadros buenos')


if __name__ == '__main__':
    main()
