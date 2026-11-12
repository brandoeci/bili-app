from __future__ import annotations

# Frases en español de Colombia, pensadas para decirse en voz alta: cortas y sin nombres de calle.
ACCIONES = {
    'DEPART': 'siga derecho',
    'STRAIGHT': 'siga derecho',
    'NAME_CHANGE': 'siga derecho',
    'TURN_LEFT': 'gire a la izquierda',
    'TURN_RIGHT': 'gire a la derecha',
    'TURN_SLIGHT_LEFT': 'gire levemente a la izquierda',
    'TURN_SLIGHT_RIGHT': 'gire levemente a la derecha',
    'TURN_SHARP_LEFT': 'gire cerrado a la izquierda',
    'TURN_SHARP_RIGHT': 'gire cerrado a la derecha',
    'UTURN_LEFT': 'dé la vuelta',
    'UTURN_RIGHT': 'dé la vuelta',
    'FORK_LEFT': 'tome el camino de la izquierda',
    'FORK_RIGHT': 'tome el camino de la derecha',
}

DESCONOCIDA = 'continúe'  # nunca "siga derecho": una maniobra desconocida puede ser un giro


def accion_de(maniobra: str | None) -> str:
    return ACCIONES.get(maniobra or 'DEPART', DESCONOCIDA)


# Bogotá cuenta en cuadras: una cuadra son unos 100 m. Es una aproximación, por eso no se usa para el aviso de giro.
# La misma regla está en web/nav.js (sayDistance); las dos se prueban con tests/fixtures/distancias.json.
METROS_POR_CUADRA = 100


def _redondear(x: float) -> int:
    return int(x + 0.5)  # igual que Math.round de JavaScript (round() de Python redondea 2.5 a 2)


def decir_distancia(metros: float) -> str:
    """Como habla quien camina: pasos y metros de cerca, cuadras de lejos. Nunca kilómetros."""
    m = max(0.0, float(metros))
    if m < 8:
        return 'unos pocos pasos'
    if m < 20:
        return f'unos {_redondear(m / 5) * 5} metros'
    if m < 100:
        return f'unos {_redondear(m / 10) * 10} metros'
    if m < 150:
        return f'unos {_redondear(m / 50) * 50} metros'
    return f'unas {max(2, _redondear(m / METROS_POR_CUADRA))} cuadras'


def frase_de_paso(accion: str, distancia_m: float, es_ultimo: bool) -> str:
    base = accion[0].upper() + accion[1:]
    # "siga derecho" ya lleva el verbo seguir: evita "Siga derecho y siga 50 metros"
    union = ' ' if accion == 'siga derecho' else ' y siga '
    if es_ultimo:
        return f'{base}{union}{decir_distancia(distancia_m)} hasta llegar a su destino'
    if distancia_m < 8:
        return base
    return f'{base}{union}{decir_distancia(distancia_m)}'


def decir_duracion(segundos: int) -> str:
    minutos = max(1, _redondear(segundos / 60))
    if minutos > 10:
        minutos = _redondear(minutos / 5) * 5
    if minutos < 60:
        return 'un minuto' if minutos == 1 else f'unos {minutos} minutos'
    horas, resto = divmod(minutos, 60)
    base = 'una hora' if horas == 1 else f'unas {horas} horas'
    return base if resto == 0 else f'{base} y {resto} minutos'


def resumen_de_ruta(distancia_m: int, duracion_s: int) -> str:
    # "o más": el tiempo de Google supone un paso de 5 km/h, y quien no ve suele ir más despacio.
    return f'Ruta a pie de {decir_distancia(distancia_m)}. Se tarda {decir_duracion(duracion_s)} o más.'


ADVERTENCIA_BILI = (
    'La ruta es solo una guía: puede no incluir andenes completos ni obstáculos. '
    'Use su bastón o perro guía.'
)
