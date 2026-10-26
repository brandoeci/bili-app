from __future__ import annotations

from unittest.mock import patch

import numpy as np

from app.audio.tts import Speaker
from app.core.quality import FrameQuality
from app.scene.prompts import build_prompt


def test_covered_camera_is_reported_once_and_recovery_too():
    quality = FrameQuality(bad_frames=3, good_frames=2)
    black = np.zeros((360, 640, 3), np.uint8)
    scene = np.random.default_rng(0).integers(0, 255, (360, 640, 3), dtype=np.uint8)
    events = [quality.check(black) for _ in range(6)]
    assert events == [None, None, 'blocked', None, None, None]
    assert [quality.check(scene) for _ in range(3)] == [None, 'ok', None]


def test_tts_falls_back_to_espeak_off_macos():
    with patch('app.audio.tts.shutil.which', side_effect=lambda c: '/usr/bin/espeak-ng' if c == 'espeak-ng' else None):
        speaker = Speaker(rate=170)
        try:
            assert speaker._command('hola') == ['espeak-ng', '-v', 'es', '-s', '170', 'hola']
        finally:
            speaker.shutdown()


def test_tts_silent_when_no_engine():
    with patch('app.audio.tts.shutil.which', return_value=None):
        speaker = Speaker()
        try:
            assert speaker.say('hola') is False
        finally:
            speaker.shutdown()


def test_prompt_includes_navigation_clearance():
    nav = {'sectors': {'left': {'state': 'free', 'clear_m': 5.0}, 'center': {'state': 'blocked', 'clear_m': 1.0},
                       'right': {'state': 'caution', 'clear_m': 2.0}}}
    prompt = build_prompt('scene', [], navigation=nav)
    assert 'frente bloqueado (1.0 m)' in prompt and 'izquierda libre' in prompt


def test_hazard_labels_are_spanish():
    from app.core.labels import label_es

    assert label_es('step_up') == 'escalón hacia arriba'
    assert label_es('stairs_down') == 'escaleras que bajan'
    assert label_es('traffic light') == 'semáforo'
