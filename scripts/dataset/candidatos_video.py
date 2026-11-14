"""Lógica pura para armar la revisión de los cuadros del video: une los candidatos del modelo (todas las clases) y de DINO (postes).

Una sola revisión por cuadro con TODAS las clases: si solo se revisara una clase, las demás cosas del cuadro quedarían sin etiqueta y el
modelo las aprendería como fondo (así se rompieron los postes en el v5)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'stride'))
from v6_logica import cubierto, iou_xyxy  # noqa: E402

# Umbral mínimo del modelo para proponer una caja de cada clase. Más bajo en las clases débiles (bordillo, hueco, escalera).
UMBRAL_MODELO = {'curb': 0.15, 'pothole': 0.15, 'stairs': 0.15, 'obstacle': 0.20, 'manhole': 0.20, 'pole': 0.30}
UMBRAL_DINO = 0.35       # entre 0,25 y 0,35 DINO propone sobre todo basura: no se revisa (más adelante se tapa, igual que en los postes del v6b)
FORMA_DINO = 1.5          # alto/ancho mínimo de una caja de poste


def unir_candidatos(modelo: list, dino: list, umbral_modelo: dict | None = None) -> list[dict]:
    """modelo: [[clase, conf, x1, y1, x2, y2]]; dino: [[x1, y1, x2, y2, score]] (postes).
    Devuelve [{'clase', 'conf', 'caja', 'fuente'}]. Una caja de DINO que coincide con un poste del modelo no se repite."""
    um = umbral_modelo or UMBRAL_MODELO
    out: list[dict] = []
    for c in sorted(modelo, key=lambda x: -x[1]):
        if c[1] < um.get(c[0], 0.25):
            continue
        caja = list(c[2:6])
        # misma clase y casi la misma caja: se queda la de mayor confianza (el modelo a veces duplica)
        if any(o['clase'] == c[0] and iou_xyxy(o['caja'], caja) >= 0.6 for o in out):
            continue
        out.append({'clase': c[0], 'conf': round(float(c[1]), 3), 'caja': caja, 'fuente': 'modelo'})
    postes = [o['caja'] for o in out if o['clase'] == 'pole']
    for d in sorted(dino, key=lambda x: -x[4]):
        w, h = d[2] - d[0], d[3] - d[1]
        if d[4] < UMBRAL_DINO or h / max(w, 1.0) < FORMA_DINO:
            continue
        caja = list(d[:4])
        if any(iou_xyxy(p, caja) >= 0.3 or cubierto(caja, p) >= 0.5 or cubierto(p, caja) >= 0.7 for p in postes):
            continue
        out.append({'clase': 'pole', 'conf': round(float(d[4]), 3), 'caja': caja, 'fuente': 'dino'})
        postes.append(caja)
    return out
