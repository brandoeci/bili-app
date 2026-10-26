"""Benchmark offline sobre videos grabados.

Uso:
    python scripts/benchmark.py clips/*.mp4 [--annotations distancias.csv] [--max-frames 300]
    python scripts/benchmark.py --report        # videostest/*.mp4 -> videostest/informes/

Reporta, por video y en total, p50/p95 por etapa (YOLO, profundidad, análisis de camino),
FPS efectivo (sin calentamiento), estabilidad del tracking y, si se da un CSV (video,t,label,meters), el error de distancia de la fusión
contra la medida real con cinta. Sirve para ajustar umbrales con datos reales."""
from __future__ import annotations

import argparse
import csv
import platform
import statistics
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.core.depth import DepthModel  # noqa: E402
from app.core.detector import YoloDetector  # noqa: E402
from app.core.fusion import FusionEngine  # noqa: E402
from app.core.navigation import PathAnalyzer  # noqa: E402
from app.core.overlay import draw_overlay  # noqa: E402

VIDEOS_DIR = Path(__file__).resolve().parent.parent / 'videostest'


def pct(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))] if ordered else float('nan')


def load_annotations(path: str | None) -> dict[str, list[tuple[float, str, float]]]:
    notes: dict[str, list[tuple[float, str, float]]] = defaultdict(list)
    if path:
        with open(path, newline='') as handle:
            for row in csv.DictReader(handle):
                notes[Path(row['video']).name].append((float(row['t']), row['label'], float(row['meters'])))
    return notes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('videos', nargs='*', help='por defecto: videostest/*.mp4')
    parser.add_argument('--report', nargs='?', const=str(VIDEOS_DIR / 'informes'), metavar='DIR',
                        help='genera un informe .md (+ imagen de muestra) por video y un resumen.md; DIR por defecto: videostest/informes')
    parser.add_argument('--annotations')
    parser.add_argument('--max-frames', type=int, default=300)
    parser.add_argument('--warmup', type=int, default=5, help='frames iniciales excluidos de tiempos (compilación MPS)')
    args = parser.parse_args()
    args.videos = args.videos or sorted(str(p) for p in VIDEOS_DIR.glob('*.mp4'))
    if not args.videos:
        parser.error('no hay videos: pasa rutas o coloca .mp4 en videostest/')
    report_dir = Path(args.report) if args.report else None
    if report_dir:
        report_dir.mkdir(parents=True, exist_ok=True)
    reports: list[dict] = []

    detector = YoloDetector(str(settings.base_dir / settings.detector_model), settings.detector_conf, settings.detector_iou,
                            device=settings.detector_device)
    depth = DepthModel(settings.depth_enabled, settings.depth_model, settings.depth_input_px)
    depth._load()  # síncrono: el benchmark necesita el modelo ya listo
    fusion, notes = FusionEngine(settings.camera_focal_ratio), load_annotations(args.annotations)
    total = Stats()
    # Calentamiento fuera de medición: la primera inferencia en MPS compila kernels.
    warm = cv2.VideoCapture(args.videos[0])
    ok, frame = warm.read()
    if ok:
        h, w = frame.shape[:2]
        small = cv2.resize(frame, (640, int(640 * h / w)))
        for _ in range(3):
            detector.track(small)
            depth.infer(small)
    detector.reset()
    errors: list[float] = []
    started = time.perf_counter()

    for video in args.videos:
        capture = cv2.VideoCapture(video)
        fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
        path, local = PathAnalyzer(), Stats()
        detector.reset()
        fusion = FusionEngine(settings.camera_focal_ratio)
        index = 0
        video_start = time.perf_counter()
        while index < args.max_frames:
            ok, frame = capture.read()
            if not ok:
                break
            h, w = frame.shape[:2]
            small = cv2.resize(frame, (640, int(640 * h / w)))
            t0 = time.perf_counter()
            dets = detector.track(small)
            t1 = time.perf_counter()
            depth_map = depth.infer(small) if depth.enabled and index % settings.depth_every_n_frames == 0 else None
            t2 = time.perf_counter()
            nav = path.analyze(depth_map) if depth_map is not None else None
            t3 = time.perf_counter()
            fused = fusion.update(dets, depth_map, small.shape)
            measured = index >= args.warmup
            if len(fused) > local.best_count:
                local.best_count = len(fused)
                local.best_frame = draw_overlay(small, fused) if report_dir else None
            for stats in (local, total):
                stats.frames += 1
                for d in dets:
                    stats.labels[d.label] += 1
                    if d.track_id is not None:
                        stats.tracks[d.track_id] += 1
                if measured:
                    stats.stages['yolo_ms'].append((t1 - t0) * 1000)
                    if depth_map is not None:
                        stats.stages['depth_ms'].append((t2 - t1) * 1000)
                        stats.stages['navigation_ms'].append((t3 - t2) * 1000)
                if nav:
                    for hz in nav.hazards:
                        stats.hazards[hz.kind] += 1
            for t, label, meters in notes.get(Path(video).name, []):
                if abs(index / fps - t) <= 0.5 / fps:
                    same = [d for d in fused if d.label == label and d.distance_m]
                    if same:
                        err = abs(same[0].distance_m - meters) / meters
                        errors.append(err)
                        local.errors.append(err)
            index += 1
        local.elapsed = time.perf_counter() - video_start
        local.meta = {'video': Path(video).name, 'size': f'{w}x{h}', 'src_fps': fps,
                      'src_frames': int(capture.get(cv2.CAP_PROP_FRAME_COUNT))}
        print(f'\n== {Path(video).name} ({w}x{h}) ==')
        local.report()
        if report_dir:
            write_video_report(report_dir, local)
            reports.append(local)

    total.elapsed = time.perf_counter() - started
    print('\n== TOTAL ==')
    total.report()
    if errors:
        print(f'Error relativo de distancia: mediana={statistics.median(errors):.1%}  p95={pct(errors, 0.95):.1%}  n={len(errors)}')
    elif args.annotations:
        print('Sin coincidencias entre anotaciones y detecciones.')
    if report_dir:
        total.errors = errors
        write_summary(report_dir, reports, total, args)
        print(f'\nInformes en {report_dir}')


class Stats:
    def __init__(self) -> None:
        self.stages: dict[str, list[float]] = defaultdict(list)
        self.hazards: dict[str, int] = defaultdict(int)
        self.tracks: dict[int, int] = defaultdict(int)  # track_id -> frames vistos
        self.labels: Counter[str] = Counter()
        self.errors: list[float] = []
        self.meta: dict = {}
        self.best_count = 0
        self.best_frame = None  # frame con más objetos, con overlay (solo si hay --report)
        self.frames = 0
        self.elapsed = 0.0

    def report(self) -> None:
        print(f'Frames: {self.frames}  FPS efectivo: {self.frames / max(1e-9, self.elapsed):.1f}')
        for name, values in self.stages.items():
            print(f'  {name:15s} p50={statistics.median(values):6.1f}  p95={pct(values, 0.95):6.1f}  n={len(values)}')
        if self.tracks:
            lengths = list(self.tracks.values())
            stable = sum(1 for n in lengths if n >= 10)
            print(f'  tracks: {len(lengths)} IDs, mediana {statistics.median(lengths):.0f} frames, {stable} estables (>=10 frames)')
        if self.hazards:
            print('  peligros (frames):', dict(self.hazards))


def stage_rows(stats: Stats) -> list[str]:
    rows = ['| Etapa | p50 (ms) | p95 (ms) | Muestras |', '|---|---|---|---|']
    for name, values in stats.stages.items():
        rows.append(f'| {name} | {statistics.median(values):.1f} | {pct(values, 0.95):.1f} | {len(values)} |')
    return rows


def tracking_line(stats: Stats) -> str:
    lengths = list(stats.tracks.values())
    if not lengths:
        return 'Sin objetos con track.'
    stable = sum(1 for n in lengths if n >= 10)
    return f'{len(lengths)} IDs, mediana {statistics.median(lengths):.0f} frames por ID, {stable} estables (≥10 frames).'


def median_ms(stats: Stats, name: str) -> str:
    return f'{statistics.median(stats.stages[name]):.1f} ms' if stats.stages.get(name) else '-'


def table(title: str, counts: dict, header: str) -> list[str]:
    if not counts:
        return []
    rows = ['', f'## {title}', '', f'| {header} | Frames |', '|---|---|']
    rows += [f'| {k} | {v} |' for k, v in sorted(counts.items(), key=lambda kv: -kv[1])]
    return rows


def write_video_report(report_dir: Path, stats: Stats) -> None:
    meta = stats.meta
    stem = Path(meta['video']).stem
    lines = [f'# Informe: {meta["video"]}', '',
             f'- **Resolución original:** {meta["size"]} · {meta["src_fps"]:.0f} fps · {meta["src_frames"]} frames',
             f'- **Frames procesados:** {stats.frames} en {stats.elapsed:.1f} s → **{stats.frames / max(1e-9, stats.elapsed):.1f} FPS efectivo** '
             '(incluye decodificar el video)',
             f'- **Tracking:** {tracking_line(stats)}', '', '## Latencia por etapa', '', *stage_rows(stats)]
    lines += table('Objetos detectados', stats.labels, 'Clase')
    lines += table('Peligros de camino', stats.hazards, 'Tipo')
    if stats.errors:
        lines += ['', '## Error de distancia', '',
                  f'Mediana {statistics.median(stats.errors):.1%} · p95 {pct(stats.errors, 0.95):.1%} · n={len(stats.errors)}']
    if stats.best_frame is not None:
        cv2.imwrite(str(report_dir / f'{stem}.jpg'), stats.best_frame)
        lines += ['', '## Muestra', '', f'Frame con más objetos ({stats.best_count}):', '', f'![{stem}]({stem}.jpg)']
    (report_dir / f'{stem}.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def write_summary(report_dir: Path, reports: list[Stats], total: Stats, args: argparse.Namespace) -> None:
    lines = ['# Resumen de pruebas con videos', '',
             f'- **Fecha:** {datetime.now():%Y-%m-%d %H:%M}',
             f'- **Equipo:** {platform.platform()} · detector en `{settings.detector_device or "auto"}`',
             f'- **Configuración:** `{settings.detector_model}`, profundidad `{settings.depth_model}` '
             f'(entrada {settings.depth_input_px}px, cada {settings.depth_every_n_frames} frames), máx. {args.max_frames} frames/video',
             '', '## Por video', '',
             '| Video | Tamaño | Frames | FPS | YOLO p50 | Profundidad p50 | Tracks estables | Peligros |',
             '|---|---|---|---|---|---|---|---|']
    for r in reports:
        stem = Path(r.meta['video']).stem
        stable = sum(1 for n in r.tracks.values() if n >= 10)
        lines.append(f'| [{r.meta["video"]}]({stem}.md) | {r.meta["size"]} | {r.frames} | {r.frames / max(1e-9, r.elapsed):.1f} | '
                     f'{median_ms(r, "yolo_ms")} | {median_ms(r, "depth_ms")} | {stable}/{len(r.tracks)} | {sum(r.hazards.values())} |')
    lines += ['', '## Total', '', f'**{total.frames} frames · {total.frames / max(1e-9, total.elapsed):.1f} FPS efectivo**', '',
              *stage_rows(total), '', f'Tracking: {tracking_line(total)}']
    lines += table('Peligros de camino', total.hazards, 'Tipo')
    if total.errors:
        lines += ['', f'Error de distancia: mediana {statistics.median(total.errors):.1%} · p95 {pct(total.errors, 0.95):.1%} · n={len(total.errors)}']
    (report_dir / 'resumen.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
