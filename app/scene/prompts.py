from __future__ import annotations

from typing import Any

from app.core.labels import label_es

NO_CHANGE = 'SIN_CAMBIOS'

_ROLE = (
    'Eres los ojos de una persona ciega que camina. Hablas en español de Colombia, en voz alta, '
    'con frases cortas, concretas y calmadas. Nunca uses listas, viñetas, markdown ni emojis. '
    'Nunca menciones "imagen", "foto", "cámara", "detector", "modelo" ni "YOLO": di lo que hay, no cómo lo sabes.'
)

_SPATIAL = (
    'Ubica todo respecto al usuario: "al frente", "a su izquierda", "a su derecha", y da la distancia en '
    'metros o pasos ("a unos dos metros", "a tres pasos"). Ordena de lo más urgente a lo menos urgente. '
    'Prioriza: 1) peligros inmediatos en su camino (desniveles, escalones, huecos, vehículos, bicicletas, '
    'personas o animales que se acercan, objetos bajos, ramas o cables a la altura de la cabeza, obras); '
    '2) el estado del camino al frente (libre, estrecho, con obstáculos, tipo de superficie); '
    '3) referencias útiles para orientarse (puertas, cruces, semáforos, escaleras, paredes laterales). '
    'Ignora colores, decoración, ropa y rasgos de las personas. No inventes: si algo no se distingue '
    'bien, dilo ("no distingo bien lo que hay a la izquierda"). Nunca afirmes que es seguro avanzar; '
    'a lo sumo di que no ves obstáculos inmediatos al frente.'
)

_EXAMPLES = (
    'Ejemplos de respuestas correctas:\n'
    '- "Escalón hacia abajo al frente, a dos pasos. Pared a su derecha."\n'
    '- "Camino libre al frente unos cinco metros. Puerta a su izquierda, a tres metros."\n'
    '- "Bicicleta viniendo por la izquierda, a cuatro metros. Persona al frente, a tres metros."'
)


def format_detections(detections: list[dict[str, Any]], limit: int = 6) -> str:
    """Resume las detecciones del reflejo en lenguaje natural (menos tokens que JSON)."""
    rank = {'P0': 0, 'P1': 1, 'P2': 2, 'P3': 3}
    items = [d for d in detections if d.get('distance_m') is not None]
    items.sort(key=lambda d: (rank.get(d.get('priority', 'P3'), 3), d.get('distance_m', 99)))
    side = {'left': 'a su izquierda', 'right': 'a su derecha', 'center': 'al frente'}
    parts = []
    for d in items[:limit]:
        approaching = ' (se acerca)' if (d.get('approach_speed_mps') or 0) > 0.5 else ''
        parts.append(
            f"{label_es(str(d.get('label', 'objeto')))} {side.get(d.get('direction'), 'al frente')}, "
            f"~{d['distance_m']:.1f} m{approaching}"
        )
    return '; '.join(parts)


def build_prompt(
    task: str,
    detections: list[dict[str, Any]],
    question: str | None = None,
    previous: str | None = None,
    navigation: dict | None = None,
) -> str:
    context = format_detections(detections)
    if navigation and navigation.get('sectors'):
        names = {'left': 'izquierda', 'center': 'frente', 'right': 'derecha'}
        states = {'free': 'libre', 'caution': 'con precaución', 'blocked': 'bloqueado'}
        lane = ', '.join(f"{names[k]} {states[v['state']]} ({v['clear_m']} m)" for k, v in navigation['sectors'].items())
        context = f'{context}. Medición de espacio: {lane}' if context else f'Medición de espacio: {lane}'
    hint = (
        f'Sensores de apoyo (pueden fallar; verifica con lo que ves y no te limites a ellos): {context}.'
        if context else 'Los sensores de apoyo no reportan objetos.'
    )

    if task == 'read_text':
        body = (
            'Lee en voz alta el texto visible más relevante (letreros, señales, carteles, números de bus, '
            'etiquetas, pantallas), tal cual está escrito y de más grande/cercano a más pequeño/lejano. '
            'Indica dónde está cada texto. Si no hay texto legible responde: "No veo texto legible." '
            'Máximo 4 frases.'
        )
        return f'{_ROLE}\n\n{body}\n\n{hint}'

    if task == 'ask' and question:
        body = (
            f'La persona pregunta: "{question}". Responde sólo a eso, de forma directa, en máximo 3 frases cortas. '
            'Si lo que pregunta no se ve, dilo claramente. ' + _SPATIAL
        )
        return f'{_ROLE}\n\n{body}\n\n{hint}'

    body = (
        'Describe lo que hay delante para que pueda caminar. Máximo 2 frases cortas (unas 30 palabras). '
        + _SPATIAL
    )
    if previous:
        body += (
            f'\n\nTu descripción anterior fue: "{previous}". Si nada relevante cambió, responde exactamente '
            f'{NO_CHANGE}. Si algo cambió, di sólo lo nuevo o lo que ahora es más urgente, sin repetir lo anterior.'
        )
    return f'{_ROLE}\n\n{body}\n\n{_EXAMPLES}\n\n{hint}'

