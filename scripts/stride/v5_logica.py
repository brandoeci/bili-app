"""Lógica pura (sin imágenes ni disco) para armar los datos del v5 a partir de las revisiones a ojo de escaleras.

Una revisión dice, por VISTA: real / falso / dudoso / mal. Las cajas las pusieron los modelos (v2 y v4), no la persona. De ahí:
  - REAL con una sola caja (o varias que coinciden entre los dos modelos): esa es la caja de la escalera -> positivo.
  - REAL con varias cajas que NO coinciden: no se sabe cuál es la buena -> ambigua, se deja fuera hasta mirarla.
  - FALSO: no hay escalera. Sirve de negativo difícil, pero solo si en la vista no hay OTRAS clases detectadas (postes, bordillos...):
    esas cosas quedarían sin etiqueta y se le enseñaría al modelo que no existen.
  - DUDOSO y MAL: fuera del entrenamiento (en MAL hay una escalera sin caja buena)."""
from __future__ import annotations

import re

VEREDICTOS = ('real', 'falso', 'dudoso', 'mal')


def parsear_listas(texto: str) -> dict[str, list[int]]:
    """'Real: 3 5 8\\nFalso: 1 2 ...' -> {'real': [3, 5, 8], 'falso': [1, 2], ...}. Tolera saltos de línea y espacios dobles."""
    partes = re.split(r'(?im)^\s*(real|falso|dudoso|mal)\s*:', texto)
    out: dict[str, list[int]] = {}
    for i in range(1, len(partes), 2):
        out.setdefault(partes[i].lower(), []).extend(int(x) for x in re.findall(r'\d+', partes[i + 1]))
    return out


def comprobar_listas(listas: dict[str, list[int]], total: int) -> dict:
    """Cobertura de una revisión: qué números faltan, cuáles se repiten, cuáles se salen del rango."""
    todos = [n for v in listas.values() for n in v]
    vistos, repetidos = set(), set()
    for n in todos:
        (repetidos if n in vistos else vistos).add(n)
    return {'faltan': sorted(set(range(1, total + 1)) - vistos), 'repetidos': sorted(repetidos), 'fuera': sorted(n for n in vistos if not 1 <= n <= total)}


def iou_xywh(a, b) -> float:
    """a, b = (conf, cx, cy, w, h) normalizados."""
    ax1, ay1, ax2, ay2 = a[1] - a[3] / 2, a[2] - a[4] / 2, a[1] + a[3] / 2, a[2] + a[4] / 2
    bx1, by1, bx2, by2 = b[1] - b[3] / 2, b[2] - b[4] / 2, b[1] + b[3] / 2, b[2] + b[4] / 2
    inter = max(0.0, min(ax2, bx2) - max(ax1, bx1)) * max(0.0, min(ay2, by2) - max(ay1, by1))
    union = a[3] * a[4] + b[3] * b[4] - inter
    return inter / union if union > 0 else 0.0


def agrupar(cajas_v2, cajas_v4, umbral_iou: float = 0.5) -> list[dict]:
    """Junta las cajas de los dos modelos que se solapan (IoU >= umbral). Cada grupo: caja promedio ponderada por confianza,
    qué modelos la marcaron y su mayor confianza. Cajas de un mismo modelo que se solapan también se funden."""
    todas = sorted([(tuple(c), 'v2') for c in cajas_v2] + [(tuple(c), 'v4') for c in cajas_v4], key=lambda x: -x[0][0])
    grupos: list[list] = []
    for caja, modelo in todas:
        for g in grupos:
            if iou_xywh(caja, g[0][0]) >= umbral_iou:
                g.append((caja, modelo))
                break
        else:
            grupos.append([(caja, modelo)])
    out = []
    for g in grupos:
        peso = sum(c[0] for c, _ in g)
        cx, cy, w, h = (sum(c[0] * c[k] for c, _ in g) / peso for k in (1, 2, 3, 4))
        out.append({'caja': (cx, cy, w, h), 'modelos': sorted({m for _, m in g}), 'conf': max(c[0] for c, _ in g)})
    return out


def clasificar_real(grupos: list[dict]) -> tuple[str, list[dict]]:
    """Una vista que la persona marcó REAL. ('positivo', [grupo]) si no hay duda sobre dónde está la escalera; si no, ('ambigua', grupos)."""
    if len(grupos) == 1:
        return 'positivo', grupos
    return 'ambigua', grupos


def negativo_limpio(otras_confianzas: dict[str, float], umbral: float = 0.35) -> bool:
    """Una vista FALSA sirve como negativo solo si ningún modelo detectó en ella OTRA clase (poste, bordillo...) con confianza >= umbral."""
    return not any(c >= umbral for c in otras_confianzas.values())


def linea_yolo(clase_id: int, caja) -> str:
    cx, cy, w, h = (min(max(float(v), 0.0), 1.0) for v in caja)
    return f'{clase_id} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}'
