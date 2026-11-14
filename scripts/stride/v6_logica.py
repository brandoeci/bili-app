"""Lógica pura (sin imágenes ni disco) para armar el v6: postes revisados a ojo sobre cajas que propuso Grounding DINO.

Problema de fondo: una vista puede tener varios postes y la caja revisada cubrir solo uno. Si se entrena así, los otros quedan como "fondo" y
el modelo aprende a ignorarlos (justo lo contrario de lo que se busca). Qué se hace con cada vista:
  - con alguna caja MAL (hay poste pero la caja está mal) o en CONFLICTO entre revisores, o marcada a mano con varios postes: FUERA.
  - con alguna caja REAL (R): POSITIVA. Las cajas D (dudoso) y las cajas de DINO/modelo que nadie revisó se TAPAN (relleno), para que un poste
    posible sin etiqueta no quede a la vista.
  - sin R pero con F (no es poste): NEGATIVA (hay que comprobar aparte que no tenga otras clases). Igual se tapan D y extras.
  - sin R ni F: FUERA."""
from __future__ import annotations

R, F, D, MAL, CONFLICTO = 'R', 'F', 'D', 'MAL', 'CONFLICTO'


def unir_veredictos(mi: dict[int, str], diego: dict[int, str]) -> dict[int, str]:
    """Une dos revisiones por número global; si dos revisores vieron la misma caja y no coinciden: CONFLICTO."""
    out: dict[int, str] = {}
    for g in set(mi) | set(diego):
        a, b = mi.get(g), diego.get(g)
        if a is None or b is None:
            out[g] = a if b is None else b
        else:
            out[g] = a if a == b else CONFLICTO
    return out


def _area(b) -> float:
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def _inter(a, b) -> float:
    return max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(0.0, min(a[3], b[3]) - max(a[1], b[1]))


def iou_xyxy(a, b) -> float:
    i = _inter(a, b)
    u = _area(a) + _area(b) - i
    return i / u if u > 0 else 0.0


def cubierto(a, b) -> float:
    """Fracción del área de `a` que cae dentro de `b`."""
    return _inter(a, b) / _area(a) if _area(a) > 0 else 0.0


def cajas_extra(candidatas, revisadas, minimo: float = 0.25, forma: float = 1.5, iou_igual: float = 0.3, cubierta_igual: float = 0.5):
    """Cajas candidatas [x1,y1,x2,y2,score] (alargadas, score >= minimo) que NO son ninguna de las ya revisadas."""
    out = []
    for c in candidatas:
        if c[4] < minimo or (c[3] - c[1]) / max(c[2] - c[0], 1.0) < forma:
            continue
        if any(iou_xyxy(c[:4], r) >= iou_igual or cubierto(c[:4], r) >= cubierta_igual for r in revisadas):
            continue
        out.append(list(c[:4]))
    return out


def plan_vista(revisadas: list[tuple[list[float], str]], extras: list[list[float]], marcada_varios: bool = False, cubierta_max: float = 0.2) -> dict:
    """revisadas: [(caja xyxy, veredicto)] de la vista. Devuelve {'accion': positivo|negativo|fuera, 'motivo', 'positivas': [caja], 'tapar': [caja]}."""
    vs = [v for _, v in revisadas]
    if marcada_varios:
        return {'accion': 'fuera', 'motivo': 'marcada con varios postes', 'positivas': [], 'tapar': []}
    if MAL in vs or CONFLICTO in vs:
        return {'accion': 'fuera', 'motivo': 'caja mal o en conflicto', 'positivas': [], 'tapar': []}
    positivas = [b for b, v in revisadas if v == R]
    # Lo que se tapa no puede pisar un poste bueno: si lo cubre en más de `cubierta_max`, no se tapa.
    tapar = [b for b in [b for b, v in revisadas if v == D] + list(extras) if all(cubierto(b, p) <= cubierta_max for p in positivas)]
    if positivas:
        return {'accion': 'positivo', 'motivo': '', 'positivas': positivas, 'tapar': tapar}
    if F in vs:
        return {'accion': 'negativo', 'motivo': '', 'positivas': [], 'tapar': tapar}
    return {'accion': 'fuera', 'motivo': 'sin cajas reales ni falsas', 'positivas': [], 'tapar': []}
