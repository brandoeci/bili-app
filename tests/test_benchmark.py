import importlib.util
from pathlib import Path

import numpy as np

spec = importlib.util.spec_from_file_location('benchmark', Path(__file__).resolve().parent.parent / 'scripts' / 'benchmark.py')
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


def make_stats() -> 'benchmark.Stats':
    stats = benchmark.Stats()
    stats.meta = {'video': 'demo.mp4', 'size': '640x360', 'src_fps': 30.0, 'src_frames': 90}
    stats.frames, stats.elapsed = 90, 3.0
    stats.stages['yolo_ms'] += [10.0, 12.0, 11.0]
    stats.labels['chair'] += 5
    stats.hazards['wall'] += 2
    stats.tracks.update({1: 20, 2: 3})
    stats.best_count, stats.best_frame = 2, np.zeros((36, 64, 3), np.uint8)
    return stats


def test_report_files(tmp_path):
    stats = make_stats()
    benchmark.write_video_report(tmp_path, stats)
    text = (tmp_path / 'demo.md').read_text(encoding='utf-8')
    assert '30.0 FPS efectivo' in text and '| chair | 5 |' in text and '1 estables' in text
    assert (tmp_path / 'demo.jpg').exists()


def test_summary_links_each_video(tmp_path):
    stats = make_stats()
    args = type('A', (), {'max_frames': 300})()
    benchmark.write_summary(tmp_path, [stats], stats, args)
    assert '[demo.mp4](demo.md)' in (tmp_path / 'resumen.md').read_text(encoding='utf-8')
