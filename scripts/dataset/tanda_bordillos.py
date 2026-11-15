"""Arma una tanda de dibujo de bordillos a partir de la revisión del video repartido (video-reparto).

Toma los cuadros de ENTRENAMIENTO donde la revisión dijo que falta un bordillo ('b' en faltan.csv) y prepara un paquete de makesense:
  imagenes/        los cuadros originales, limpios, con su nombre de siempre (IMG_0763_0123s.jpg)
  cajas_previas/   un .txt YOLO por imagen con las cajas de bordillo que la revisión marcó como reales (R), y labels.txt;
                   se importan en makesense para no volver a dibujarlas. Las MAL y las dudosas (D) no van: se dibujan de nuevo.
Los cuadros de examen nunca entran. Los que no tienen ninguna caja no están en el mapa (no se sabe si son de examen) y tampoco entran.

Uso: python -I scripts/dataset/tanda_bordillos.py --reparto ~/Downloads/video-reparto --revisor diego \
       --cuadros data/video-0763/cuadros --out ~/Downloads/bordillos-tanda1 --tanda 1 --por-tanda 40"""
import argparse
import csv
import shutil
import sys
import zipfile
from pathlib import Path

ANCHO, ALTO = 720, 1280   # cuadros de video-0763, verticales


def leer_respuestas(ruta: Path) -> dict[int, list[str]]:
    filas = list(csv.reader(open(ruta, encoding='utf-8-sig')))[1:]
    return {int(r[0]): r[1].split() for r in filas if r and r[0].strip().isdigit()}


def linea_yolo(x1: float, y1: float, x2: float, y2: float) -> str:
    return f'0 {(x1 + x2) / 2 / ANCHO:.6f} {(y1 + y2) / 2 / ALTO:.6f} {(x2 - x1) / ANCHO:.6f} {(y2 - y1) / ALTO:.6f}'


def candidatos(mapa: list[dict], faltan: dict[int, list[str]], veredictos: dict[int, str], revisor: str):
    """Cuadros de entrenamiento con bordillo faltante, en orden, con sus cajas de bordillo reales."""
    por_cuadro: dict[int, dict] = {}
    for r in mapa:
        if r['revisor'] != revisor:
            continue
        c = por_cuadro.setdefault(int(r['cuadro_local']), {'archivo': r['cuadro'], 'tramos': set(), 'reales': []})
        c['tramos'].add(r['tramo'])
        if r['clase'] == 'curb' and veredictos.get(int(r['caja_local'])) == 'R':
            c['reales'].append(linea_yolo(*(float(r[k]) for k in ('x1', 'y1', 'x2', 'y2'))))
    return [(k, c) for k, c in sorted(por_cuadro.items()) if c['tramos'] == {'train'} and 'b' in faltan.get(k, [])]


PASO_PREVIAS = """ 4. Cargue las cajas que ya estaban: Actions -> Import Annotations -> YOLO, y seleccione TODOS los archivos de cajas_previas/
    (los .txt y labels.txt). Deben aparecer cajas en {con_previas} imagenes. Si no aparece nada, siga igual y avise.
"""

LEEME = """DIBUJAR BORDILLOS - tanda {tanda} ({n} imagenes). Una sola cosa: rectangulos sobre los bordillos.

En todas estas imagenes la revision dijo que FALTA al menos un bordillo: en cada una hay por lo menos uno por dibujar.

HERRAMIENTA: makesense.ai (en el navegador, sin cuenta). Si algun paso no se parece a lo que ve, mande una captura.
 1. Entre a https://www.makesense.ai y pulse "Get Started".
 2. Arrastre TODAS las imagenes de la carpeta imagenes/ y pulse "Object Detection".
 3. Cree UNA sola etiqueta: escriba  curb  y confirme. Pulse "Start project".
{paso_previas} - En cada imagen dibuje los bordillos (arrastrando el mouse) con la etiqueta curb.
 - Al terminar: Actions -> Export Annotations -> formato YOLO. Guarde el zip que baja y mandelo.
 Pruebe primero con 3 imagenes y mire que el zip traiga un .txt por imagen.

COMO DIBUJAR (la misma regla de la ronda anterior):
 - Un rectangulo AJUSTADO por cada tramo visible de bordillo, que incluya la cara vertical y el borde de arriba.
 - Cada caja mide mas o menos entre 1/4 y 1/3 del ancho de la imagen. Un bordillo largo se parte en 2 o 3 cajas seguidas.
 - Solo la parte CERCANA. No dibuje tramos lejanos ni muy pequenos (menos de ~5 % del ancho).
 - En una esquina: una caja por cada lado.
 - Si un carro o una persona tapa el bordillo, dibuje solo lo que se ve.
 - Si el borde es plano y no se ve cara vertical, NO es bordillo. Los pintados de amarillo o azul SI cuentan.
 - Los bolardos (postecitos rayados) NO son bordillo.
 - Si una caja que ya venia esta mal, borrela y dibujela bien.
 - IMPORTANTE: dibuje TODOS los bordillos cercanos de cada imagen. Un bordillo sin caja le ensena al modelo que eso no es bordillo.

NO cambie los nombres de las imagenes. Dibuje SOLO bordillos, nada mas.
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--reparto', type=Path, required=True)
    ap.add_argument('--revisor', default='diego', help="mitad del video repartido: 'diego' o 'yo' (nombre de la columna revisor del mapa)")
    ap.add_argument('--cuadros', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--tanda', type=int, default=1)
    ap.add_argument('--por-tanda', type=int, default=40)
    a = ap.parse_args()
    if a.out.exists():
        sys.exit('La salida ya existe: no la piso.')

    mapa = list(csv.DictReader(open(a.reparto / 'MAPA_MAESTRO_no_enviar.csv', encoding='utf-8-sig')))
    faltan = leer_respuestas(a.reparto / f'respuestas_{a.revisor}_faltan.csv')
    veredictos = {k: v[0].upper() for k, v in leer_respuestas(a.reparto / f'respuestas_{a.revisor}_cajas.csv').items() if v}
    todos = candidatos(mapa, faltan, veredictos, a.revisor)
    tanda = todos[(a.tanda - 1) * a.por_tanda: a.tanda * a.por_tanda]
    if not tanda:
        sys.exit(f'No hay cuadros para la tanda {a.tanda} (hay {len(todos)} en total).')

    con_previas = sum(1 for _, c in tanda if c['reales'])
    (a.out / 'imagenes').mkdir(parents=True)
    if con_previas:   # sin cajas previas no hay nada que importar: ni carpeta ni paso en el instructivo
        (a.out / 'cajas_previas').mkdir()
        (a.out / 'cajas_previas' / 'labels.txt').write_text('curb\n', encoding='utf-8')
    with open(a.out.parent / f'{a.out.name}_MAPA_no_enviar.csv', 'w', newline='', encoding='utf-8') as fm:
        w = csv.writer(fm)
        w.writerow(['archivo', 'cuadro_local', 'revisor', 'cajas_previas'])
        for k, c in tanda:
            shutil.copy2(a.cuadros / c['archivo'], a.out / 'imagenes' / c['archivo'])
            if con_previas:
                (a.out / 'cajas_previas' / (Path(c['archivo']).stem + '.txt')).write_text(''.join(l + '\n' for l in c['reales']), encoding='utf-8')
            w.writerow([c['archivo'], k, a.revisor, len(c['reales'])])
    paso = PASO_PREVIAS.format(con_previas=con_previas) if con_previas else ''
    (a.out / 'LEEME.txt').write_text(LEEME.format(tanda=a.tanda, n=len(tanda), paso_previas=paso), encoding='utf-8')

    with zipfile.ZipFile(a.out.parent / f'{a.out.name}.zip', 'w', zipfile.ZIP_DEFLATED) as z:
        for p in sorted(a.out.rglob('*')):
            if p.is_file():
                z.write(p, Path(a.out.name) / p.relative_to(a.out))
    total = -(-len(todos) // a.por_tanda)
    print(f'tanda {a.tanda} de {total}: {len(tanda)} imágenes, {con_previas} con cajas previas '
          f'({sum(len(c["reales"]) for _, c in tanda)} cajas) -> {a.out}.zip')


if __name__ == '__main__':
    main()
