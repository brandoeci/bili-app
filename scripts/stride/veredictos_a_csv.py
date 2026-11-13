"""Convierte las listas de una revisión ("Real: 3 5 8 / Falso: ... / Dudoso: ... / Mal: ...", con los números del paquete que se le dio al
revisor) a una tabla por vista con el número GLOBAL: global, origen, vista, veredicto. Se pueden juntar varios paquetes en una misma tabla.

Uso:
  python -I scripts/stride/veredictos_a_csv.py --lista diego_parte1.txt --paquete 1 --reparto CARPETA_escaleras-reparto \
         --cajas CARPETA_escaleras-entrenable/cajas_modelos.json --salida veredictos_globales.csv [--agregar]

  --paquete 1: los números son los de 'para-diego' (1..405).   --paquete 2: los de 'para-diego-parte-2' (406..791).
  --agregar: suma a una tabla existente en vez de crearla (error si una vista ya tiene veredicto distinto)."""
import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from v5_logica import comprobar_listas, parsear_listas  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--lista', type=Path, required=True)
    ap.add_argument('--paquete', type=int, choices=(1, 2), required=True)
    ap.add_argument('--reparto', type=Path, required=True)
    ap.add_argument('--cajas', type=Path, required=True)
    ap.add_argument('--salida', type=Path, required=True)
    ap.add_argument('--agregar', action='store_true')
    a = ap.parse_args()

    maestro = list(csv.DictReader(open(a.reparto / 'MAPA_MAESTRO_no_enviar.csv', encoding='utf-8-sig')))
    if a.paquete == 1:
        local_a_global = {int(r['local_para_diego']): int(r['global']) for r in maestro if r['local_para_diego']}
        rango = (1, 405)
    else:
        mi_a_global = {int(r['local_para_mi']): int(r['global']) for r in maestro if r['local_para_mi']}
        parte2 = list(csv.DictReader(open(a.reparto / 'MAPA_parte2_no_enviar.csv', encoding='utf-8-sig')))
        local_a_global = {int(r['local_diego_parte2']): mi_a_global[int(r['local_para_mi'])] for r in parte2}
        rango = (min(local_a_global), max(local_a_global))
    listas = parsear_listas(a.lista.read_text(encoding='utf-8'))
    esperados = set(local_a_global)
    hechos = {n for v in listas.values() for n in v}
    repetidos = sorted(n for n in hechos if sum(n in v for v in listas.values()) > 1)
    fuera = sorted(hechos - esperados)
    faltan = sorted(esperados - hechos)
    print({k: len(v) for k, v in listas.items()}, '| repetidos:', repetidos, '| fuera del paquete:', fuera, '| sin clasificar:', len(faltan))
    if repetidos or fuera:
        sys.exit('Hay números repetidos o fuera del paquete: revise la lista antes de seguir.')

    cajas = json.load(open(a.cajas, encoding='utf-8'))
    filas = {}
    if a.agregar and a.salida.exists():
        for r in csv.DictReader(open(a.salida, encoding='utf-8-sig')):
            filas[int(r['global'])] = r
    nuevas = 0
    for veredicto, nums in listas.items():
        for n in nums:
            g = local_a_global[n]
            info = cajas[f'{g:04d}']
            previo = filas.get(g)
            if previo and previo['veredicto'] != veredicto:
                sys.exit(f'La vista global {g} ya tiene veredicto "{previo["veredicto"]}" y ahora llega "{veredicto}".')
            if not previo:
                nuevas += 1
            filas[g] = {'global': g, 'origen': info['origen'], 'vista': info['vista'], 'veredicto': veredicto}
    with open(a.salida, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=['global', 'origen', 'vista', 'veredicto'])
        w.writeheader()
        w.writerows(filas[g] for g in sorted(filas))
    print(f'{nuevas} vistas nuevas -> {a.salida} ({len(filas)} en total)')


if __name__ == '__main__':
    main()
