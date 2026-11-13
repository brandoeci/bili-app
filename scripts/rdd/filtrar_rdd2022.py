"""Subconjunto de RDD2022 (ya convertido a YOLO) con las cajas más confiables como "hueco".

Reglas, sacadas de revisar una muestra a ojo (India traía cajas enormes sobre calzada rugosa o tierra, no huecos):
  - se excluyen los países indicados (por defecto India);
  - se descarta la IMAGEN COMPLETA si alguna de sus cajas ocupa más de --max-area de la imagen (rodadas, ondulaciones, tramos).
    Se descarta toda la imagen y no solo la caja: si no, esa zona dañada quedaría como "fondo" y se le enseñaría al modelo lo contrario.

Uso: python -I scripts/rdd/filtrar_rdd2022.py --entrada CARPETA --salida CARPETA [--excluir India] [--max-area 0.03]
"""
import argparse
import csv
import shutil
from collections import Counter
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--entrada', required=True)
    ap.add_argument('--salida', required=True)
    ap.add_argument('--excluir', default='India')
    ap.add_argument('--max-area', type=float, default=0.03)
    a = ap.parse_args()
    ent, sal = Path(a.entrada), Path(a.salida)
    excluir = set(filter(None, a.excluir.split(',')))
    (sal / 'images').mkdir(parents=True, exist_ok=True)
    (sal / 'labels').mkdir(parents=True, exist_ok=True)

    motivo = Counter()
    quedan = Counter()
    cajas = Counter()
    with open(ent / 'resumen.csv', encoding='utf-8') as f, open(sal / 'resumen.csv', 'w', newline='', encoding='utf-8') as g:
        w = csv.writer(g)
        w.writerow(['imagen', 'pais', 'cajas'])
        for r in csv.DictReader(f):
            if r['pais'] in excluir:
                motivo['pais excluido'] += 1
                continue
            lab = ent / 'labels' / (Path(r['imagen']).stem + '.txt')
            lineas = [l for l in lab.read_text(encoding='utf-8').splitlines() if l.strip()]
            if any(float(l.split()[3]) * float(l.split()[4]) > a.max_area for l in lineas):
                motivo['caja gigante'] += 1
                continue
            shutil.copy2(ent / 'images' / r['imagen'], sal / 'images' / r['imagen'])
            shutil.copy2(lab, sal / 'labels' / lab.name)
            w.writerow([r['imagen'], r['pais'], len(lineas)])
            quedan[r['pais']] += 1
            cajas[r['pais']] += len(lineas)
    (sal / 'classes.txt').write_text('pothole\n', encoding='utf-8')
    print('imagenes que quedan:', sum(quedan.values()), '| cajas:', sum(cajas.values()))
    for p in sorted(quedan):
        print(f'  {p:16s} {quedan[p]:5d} imagenes {cajas[p]:5d} cajas')
    print('descartadas:', dict(motivo))


if __name__ == '__main__':
    main()
