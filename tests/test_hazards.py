from __future__ import annotations

import numpy as np

from app.core.fusion import FusionEngine
from app.core.labels import GROUND, HAZARDS, gender_article, label_es
from app.schemas import Detection

W, H = 640, 480


def _det(label: str, bbox: tuple[int, int, int, int]) -> Detection:
    return Detection(track_id=1, label=label, conf=0.9, bbox=bbox)


def test_new_labels_are_spoken_in_spanish():
    assert label_es('pothole') == 'hueco' and label_es('curb') == 'bordillo'
    assert label_es('pole') == 'poste' and label_es('manhole') == 'tapa de alcantarilla'
    assert gender_article('manhole') == 'una' and gender_article('pothole') == 'un'
    assert {'pothole', 'curb'} <= HAZARDS and GROUND == {'pothole', 'manhole', 'curb'}


def test_ground_distance_shrinks_as_the_hazard_gets_lower_in_the_image():
    fusion = FusionEngine(focal_ratio=0.8)
    far = fusion._ground_distance((300, 260, 340, 280), W, H)     # base apenas bajo el horizonte
    near = fusion._ground_distance((250, 400, 390, 470), W, H)    # base casi al borde inferior
    assert near < far
    # Con el celular a 1,3 m mirando al frente, el borde inferior de la imagen equivale a ~2,8 m:
    # más cerca no se ve el suelo.
    assert 2.5 < near < 3.2
    assert fusion._ground_distance((300, 100, 340, 200), W, H) == 10.0   # sobre el horizonte: lejano


def test_pothole_is_not_measured_by_its_height():
    """Un hueco es plano: con la altura del bbox saldría una distancia absurda."""
    fusion = FusionEngine(focal_ratio=0.8)
    flat = _det('pothole', (200, 400, 440, 440))                  # ancho, casi sin altura
    out = fusion.update([flat], None, (H, W, 3))[0]
    assert out.distance_m < 4.0
    assert out.priority == 'P0'                                   # hueco a menos de ~5 pasos
    assert out.direction == 'center'


def test_far_pothole_is_not_urgent():
    fusion = FusionEngine(focal_ratio=0.8)
    out = fusion.update([_det('pothole', (300, 262, 330, 272))], None, (H, W, 3))[0]
    assert out.distance_m > 5.0 and out.priority != 'P0'
