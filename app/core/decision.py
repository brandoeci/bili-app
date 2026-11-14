"""Motor de decisión: de la confianza del detector a una de tres conductas (paper, entrega 2, "De la confianza del modelo a la decisión de hablar").

  avisar         confianza >= umbral ALTO de la clase: se nombra el obstáculo y el lado.
  incertidumbre  confianza entre el BAJO y el ALTO: se pide detenerse SIN nombrar la clase (QA-3).
  callar         confianza < BAJO, o la detección no es relevante (prioridad P3: lejos, a un lado, una tapa puesta...).

Primero se mira la relevancia y después la confianza: "callar cuando no hay nada relevante" vale para las tres. QA-3 se cumple así: toda
detección RELEVANTE con confianza en la banda intermedia sale como `incertidumbre`; ninguna se afirma como clase.

Umbrales medidos con el v7a en el conjunto de prueba (scripts/movil/umbrales_abstencion.py): precisión por franja de confianza.
  ALTO: desde donde la franja acierta en general más de la mitad de las veces (escaleras 0,50 como el umbral que ya usaba la app).
  BAJO: por debajo, la franja acierta 1 de cada 4 o menos: es ruido.
Ganancia medida (fracción de objetos reales que reciben algún aviso): escaleras 0,47 -> 0,58; huecos 0,49 -> 0,62; bordillos 0,36 -> 0,46;
postes 0,26 -> 0,36. Son valores de un solo modelo y del conjunto de prueba general, no de la vista del celular: se ajustan en la config.
Las clases sin tabla (las 80 de COCO) no tienen banda intermedia: se comportan como antes."""
from __future__ import annotations

from typing import Literal

Conducta = Literal['avisar', 'incertidumbre', 'callar']

# clase -> (bajo, alto)
UMBRALES: dict[str, tuple[float, float]] = {
    'pothole': (0.25, 0.50),
    'curb': (0.25, 0.50),
    'stairs': (0.25, 0.50),
    'pole': (0.30, 0.40),
    'obstacle': (0.25, 0.40),
    'manhole': (0.35, 0.35),
}


def normalizar(label: str) -> str:
    """El v2 tenía stairs_up y stairs_down; comparten los umbrales de 'stairs'."""
    label = label.lower()
    return 'stairs' if label.startswith('stairs') else label


def umbrales(label: str, tabla: dict[str, tuple[float, float]] | None = None, por_defecto: float = 0.35) -> tuple[float, float]:
    t = UMBRALES if tabla is None else tabla
    return tuple(t.get(normalizar(label), (por_defecto, por_defecto)))  # type: ignore[return-value]


def conducta(label: str, conf: float, priority: str, tabla: dict[str, tuple[float, float]] | None = None, por_defecto: float = 0.35) -> Conducta:
    """La incertidumbre solo se declara si lo detectado está cerca o en el camino (P0/P1): pedir que alguien se detenga por algo dudoso,
    lejano o a un lado (P2) sería ruido, y un sistema que habla todo el tiempo se deja de escuchar."""
    if priority == 'P3':
        return 'callar'
    bajo, alto = umbrales(label, tabla, por_defecto)
    if conf >= alto:
        return 'avisar'
    if conf >= bajo and priority in ('P0', 'P1'):
        return 'incertidumbre'
    return 'callar'


def confianza_minima(tabla: dict[str, tuple[float, float]] | None = None) -> float:
    """El detector tiene que dejar pasar todo lo que esté por encima del menor umbral BAJO, o la banda intermedia nunca existe."""
    t = UMBRALES if tabla is None else tabla
    return min(b for b, _ in t.values())
