from __future__ import annotations

import numpy as np

from app.core.navigation import PathAnalyzer

H, W, HORIZON, K = 144, 256, 50, 121.0


def floor_depth() -> np.ndarray:
    depth = np.full((H, W), 15.0, dtype=np.float32)
    for y in range(HORIZON + 3, H):
        depth[y, :] = min(15.0, K / (y - HORIZON))
    return depth


def analyze(depth, times=4):
    analyzer = PathAnalyzer()
    for _ in range(times):
        result = analyzer.analyze(depth)
    return result


def kinds(result):
    return {(h.kind, h.direction) for h in result.hazards}


def test_open_floor_has_no_hazards():
    result = analyze(floor_depth())
    assert result.floor_ok and result.hazards == []
    assert all(s['state'] == 'free' for s in result.sectors.values())
    assert result.suggestion is None


def test_wall_ahead_with_free_side():
    depth = floor_depth()
    depth[20:, 85:171] = 1.2  # pared frontal sólo en el centro
    result = analyze(depth)
    wall = [h for h in result.hazards if h.kind == 'wall' and h.direction == 'center'][0]
    assert 1.0 < wall.distance_m < 1.5
    assert result.sectors['center']['state'] == 'blocked'
    assert result.suggestion in {'left', 'right'}
    assert 'Libre hacia' in wall.note


def test_full_wall_means_stop():
    result = analyze(np.full((H, W), 0.9, dtype=np.float32))
    assert ('wall', 'center') in kinds(result)
    center = [h for h in result.hazards if h.direction == 'center'][0]
    assert result.suggestion == 'stop' and 'deténgase' in center.note


def test_close_unclassified_object_is_reported():
    depth = floor_depth()
    depth[30:125, 115:140] = 1.5  # objeto estrecho cerca, sin clase YOLO
    assert ('obstacle', 'center') in kinds(analyze(depth))


def test_drop_ahead():
    depth = floor_depth()
    depth[70:100, :] *= 3.0  # el suelo "desaparece" más lejos de lo esperado
    result = analyze(depth)
    drop = [h for h in result.hazards if h.kind in {'drop', 'stairs_down'} and h.direction == 'center']
    assert drop and 1.5 < drop[0].distance_m < 5


def test_step_up():
    depth = floor_depth()
    depth[85:100, :] /= 1.8
    assert any(k[0] in {'step_up', 'stairs_up'} and k[1] == 'center' for k in kinds(analyze(depth)))


def test_single_noisy_frame_is_not_reported():
    analyzer = PathAnalyzer()
    for _ in range(3):
        analyzer.analyze(floor_depth())
    depth = floor_depth()
    depth[70:100, :] *= 3.0
    assert analyzer.analyze(depth).hazards == []
