from __future__ import annotations

import importlib.util
from pathlib import Path

import cv2
import numpy as np

_spec = importlib.util.spec_from_file_location(
    'extract_frames', Path(__file__).resolve().parent.parent / 'scripts' / 'dataset' / 'extract_frames.py')
ef = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ef)


def _video(path: Path, frames: list[np.ndarray], fps: int = 10) -> None:
    h, w = frames[0].shape[:2]
    out = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'mp4v'), fps, (w, h))
    for f in frames:
        out.write(f)
    out.release()


def _textured(seed: int) -> np.ndarray:
    return np.random.default_rng(seed).integers(0, 255, (120, 160, 3), dtype=np.uint8)


def test_saves_distinct_sharp_frames_and_skips_repeats_and_blur(tmp_path):
    # 4 s a 10 fps, un fotograma por segundo: 0-1 s nítido A, 1-2 s igual (repetido), 2-3 s nítido B, 3-4 s borroso
    a, b = _textured(1), _textured(2)
    blurry = cv2.GaussianBlur(_textured(3), (31, 31), 0)
    frames = [a] * 10 + [a] * 10 + [b] * 10 + [blurry] * 10
    video = tmp_path / 'ruta.mp4'
    _video(video, frames)
    stats = ef.extract(video, tmp_path / 'out', every=1.0, min_blur=40.0, min_diff=4.0, max_side=1280)
    assert stats['guardados'] == 2
    assert stats['repetidos'] == 1 and stats['borrosos'] == 1
    assert len(list((tmp_path / 'out').glob('ruta_t*.jpg'))) == 2


def test_downscales_large_frames(tmp_path):
    big = cv2.resize(_textured(4), (1920, 1080), interpolation=cv2.INTER_NEAREST)
    video = tmp_path / 'g.mp4'
    _video(video, [big] * 10)
    ef.extract(video, tmp_path / 'o', every=1.0, min_blur=0.0, min_diff=0.0, max_side=640)
    img = cv2.imread(str(next((tmp_path / 'o').glob('*.jpg'))))
    assert max(img.shape[:2]) == 640
