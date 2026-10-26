from __future__ import annotations

from app.core.alerts import AlertManager
from app.core.fusion import FusionEngine
from app.schemas import Detection


def det(track=1, label='person', direction='center', distance=2.0, priority='P1', ttc=None):
    return Detection(track_id=track, label=label, conf=0.9, bbox=(0, 0, 10, 10), direction=direction,
                     distance_m=distance, priority=priority, ttc_s=ttc)


def test_static_object_is_announced_once():
    manager = AlertManager(min_frames=1)
    assert len(manager.evaluate([det()], now=0.0)) == 1
    for t in range(1, 40):
        assert manager.evaluate([det()], now=float(t)) == []  # P1 estático nunca se repite


def test_closer_band_is_announced_again():
    manager = AlertManager()
    manager.evaluate([det(distance=4.0)], now=0.0)
    alerts = manager.evaluate([det(distance=2.0)], now=2.0)
    assert len(alerts) == 1 and 'ahora' in alerts[0].text


def test_p0_gets_spaced_reminder_only():
    manager = AlertManager(reminder_s=12)
    p0 = det(distance=1.0, priority='P0')
    assert len(manager.evaluate([p0], now=0.0)) == 1
    for t in range(1, 12):
        assert manager.evaluate([p0], now=float(t)) == []
    assert len(manager.evaluate([p0], now=12.5)) == 1


def test_single_frame_flicker_is_ignored_for_non_critical():
    manager = AlertManager(min_frames=2)
    assert manager.evaluate([det()], now=0.0) == []
    assert len(manager.evaluate([det()], now=0.1)) == 1


def test_untracked_objects_do_not_spam():
    manager = AlertManager()
    total = sum(len(manager.evaluate([det(track=None)], now=t * 0.1)) for t in range(100))
    assert total == 1


def test_phrases_are_spoken_spanish_with_distance():
    text = AlertManager(min_frames=1).evaluate([det(direction='left', distance=1.0, priority='P0')], now=0.0)[0].text
    assert text.startswith('Cuidado: persona a su izquierda, a un metro')


def test_fusion_distance_uses_class_height_and_priority():
    out = FusionEngine().update([Detection(label='person', bbox=(300, 20, 360, 470), conf=0.9)], None, (480, 640, 3))[0]
    assert out.direction == 'center' and 1.0 < out.distance_m < 2.0
    assert out.priority in {'P0', 'P1'}


def test_far_side_chair_is_not_alerted():
    out = FusionEngine().update([Detection(label='chair', bbox=(10, 200, 40, 240), conf=0.9)], None, (480, 640, 3))[0]
    assert out.priority == 'P3'


def test_calibration_makes_known_distance_exact():
    fusion = FusionEngine()
    bbox = (300, 20, 360, 470)
    fusion.calibrate('person', bbox, 640, 3.0)
    out = fusion.update([Detection(label='person', bbox=bbox, conf=0.9)], None, (480, 640, 3))[0]
    assert abs(out.distance_m - 3.0) < 0.05


def test_clipped_person_uses_width_instead_of_truncated_height():
    # persona pegada a la cámara: bbox ancho y recortado arriba/abajo
    out = FusionEngine().update([Detection(label='person', bbox=(150, 0, 450, 480), conf=0.9)], None, (480, 640, 3))[0]
    assert out.distance_m < 1.5


def test_wall_alert_includes_where_you_can_go():
    manager = AlertManager()
    wall = Detection(track_id=-1, label='wall', conf=0.6, direction='center', distance_m=1.0,
                     priority='P0', note='Libre hacia la derecha.')
    text = manager.evaluate([wall], now=0.0)[0].text
    assert text == 'Cuidado: pared al frente, a un metro. Libre hacia la derecha.'
