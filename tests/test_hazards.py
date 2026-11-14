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
    assert {'pothole', 'curb'} <= HAZARDS and {'pothole', 'manhole', 'curb', 'pole', 'obstacle', 'stairs'} <= GROUND


def test_ground_distance_shrinks_as_the_hazard_gets_lower_in_the_image():
    fusion = FusionEngine(focal_ratio=0.8)
    far = fusion._ground_distance((300, 260, 340, 280), W, H)     # base apenas bajo el horizonte
    near = fusion._ground_distance((250, 400, 390, 470), W, H)    # base casi al borde inferior
    assert near < far
    # Con el celular a 1,3 m mirando al frente, el borde inferior de la imagen equivale a ~2,8 m:
    # más cerca no se ve el suelo.
    assert 2.5 < near < 3.2
    assert fusion._ground_distance((300, 100, 340, 200), W, H) == 10.0   # sobre el horizonte: lejano


def test_pole_is_measured_from_its_base_not_its_height():
    """Un poste cortado por arriba medido con 0,7 m de altura saldría a ~1 m aunque esté lejos."""
    fusion = FusionEngine(focal_ratio=0.8)
    lejos = fusion.update([_det('pole', (300, 0, 330, 300))], None, (H, W, 3))[0]    # base apenas bajo el horizonte
    assert lejos.distance_m > 5.0


def test_base_cut_by_the_bottom_edge_is_never_farther_than_the_edge_distance():
    fusion = FusionEngine(focal_ratio=0.8)
    entera = fusion._ground_distance((250, 300, 390, 470), W, H)
    cortada = fusion._ground_distance((250, 300, 390, 480), W, H)
    assert cortada < entera and cortada < 2.0


def test_small_objects_have_their_own_height():
    # Mismo tamaño en pantalla: un portátil (0,28 m) está mucho más cerca que lo que daría el 0,7 m por defecto.
    # Un motor por clase: con el mismo track_id el suavizado mezclaría las dos medidas.
    laptop = FusionEngine(focal_ratio=0.8).update([_det('laptop', (200, 200, 440, 330))], None, (H, W, 3))[0].distance_m
    otro = FusionEngine(focal_ratio=0.8).update([_det('kite', (200, 200, 440, 330))], None, (H, W, 3))[0].distance_m
    assert laptop < otro * 0.5


def test_pothole_is_not_measured_by_its_height():
    """Un hueco es plano: con la altura del bbox saldría una distancia absurda."""
    fusion = FusionEngine(focal_ratio=0.8)
    flat = _det('pothole', (200, 400, 440, 440))                  # ancho, casi sin altura
    out = fusion.update([flat], None, (H, W, 3))[0]
    assert out.distance_m < 4.0
    assert out.priority == 'P0'                                   # hueco a menos de ~5 pasos
    assert out.direction == 'center'


def test_manhole_cover_is_never_announced():
    """Una tapa puesta no es peligro: aunque esté en el camino y cerca, queda en P3 (el gestor de alertas no habla P3)."""
    fusion = FusionEngine(focal_ratio=0.8)
    out = fusion.update([_det('manhole', (200, 440, 440, 470))], None, (H, W, 3))[0]
    assert out.direction == 'center' and out.distance_m < 3.0     # antes de este cambio, aquí se avisaba (P2)
    assert out.priority == 'P3'


def test_far_pothole_is_not_urgent():
    fusion = FusionEngine(focal_ratio=0.8)
    out = fusion.update([_det('pothole', (300, 262, 330, 272))], None, (H, W, 3))[0]
    assert out.distance_m > 5.0 and out.priority != 'P0'
