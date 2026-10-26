from __future__ import annotations

import re

from app.core.alerts import AlertManager
from app.core.labels import label_es
from app.scene.prompts import NO_CHANGE

_PREAMBLE = re.compile(r'^(claro|por supuesto|ok|vale|en (la|esta) (imagen|foto|escena)[^,.:]*[,:.]?)\s*[,:.]?\s*', re.I)
_MARKUP = re.compile(r'[*_`#>\[\]]+|^\s*[-•]\s*', re.M)
_CLEAR_CLAIM = re.compile(r'(despejad|libre|no veo (ning|obst|riesg)|sin obst)', re.I)
_SIDE = {'left': 'a su izquierda', 'right': 'a su derecha', 'center': 'al frente'}
_MAX_CHARS = 320


def clean(text: str | None, max_chars: int = _MAX_CHARS) -> str | None:
    """Normaliza la salida del modelo para ser dicha en voz alta."""
    if not text:
        return None
    text = _MARKUP.sub(' ', text)
    text = ' '.join(text.split())
    text = _PREAMBLE.sub('', text).strip()
    if not text:
        return None
    if len(text) > max_chars:
        cut = text[:max_chars]
        end = max(cut.rfind('.'), cut.rfind('!'), cut.rfind('?'))
        text = cut[: end + 1] if end > 60 else cut.rstrip(' ,;') + '.'
    return text[0].upper() + text[1:]


def is_no_change(text: str | None) -> bool:
    return bool(text) and NO_CHANGE.casefold() in text.casefold().replace(' ', '_')


def reconcile_with_sensors(text: str, detections: list[dict]) -> str:
    """Red de seguridad: si el modelo dice que el camino está libre pero el
    reflejo ve algo cercano y crítico que no menciona, se añade la advertencia."""
    if not _CLEAR_CLAIM.search(text):
        return text
    lowered = text.casefold()
    missing = [
        d for d in detections
        if d.get('priority') in {'P0', 'P1'}
        and d.get('distance_m') is not None
        and label_es(str(d.get('label'))).casefold() not in lowered
    ]
    if not missing:
        return text
    missing.sort(key=lambda d: d['distance_m'])
    d = missing[0]
    extra = (
        f"Atención: {label_es(str(d['label']))} {_SIDE.get(d.get('direction'), 'al frente')}, "
        f"{AlertManager.spoken_distance(float(d['distance_m']))}."
    )
    return f'{extra} {text}'
