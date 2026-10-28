"""Saca fotogramas de videos grabados con el celular para etiquetarlos en Roboflow.

    python scripts/dataset/extract_frames.py data/bogota/videos/ruta1.mp4 --out data/bogota/frames --every 1.0

Guarda un JPG cada `--every` segundos y descarta los casi idénticos al anterior (persona parada) y los
borrosos. Los nombres llevan el video y el segundo (`ruta1_t0012.5.jpg`) para poder volver al video.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np

VIDEO_EXT = {'.mp4', '.mov', '.m4v', '.avi', '.mkv', '.webm'}


def blur_score(gray: np.ndarray) -> float:
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def differs(prev: np.ndarray | None, gray: np.ndarray, min_diff: float) -> bool:
    if prev is None:
        return True
    small = cv2.resize(gray, (64, 64))
    return float(np.abs(small.astype(np.float32) - prev.astype(np.float32)).mean()) >= min_diff


def extract(video: Path, out: Path, every: float, min_blur: float, min_diff: float, max_side: int) -> dict[str, int]:
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise SystemExit(f'No pude abrir {video}')
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    step = max(1, round(fps * every))
    out.mkdir(parents=True, exist_ok=True)
    stats = {'leidos': 0, 'guardados': 0, 'borrosos': 0, 'repetidos': 0}
    prev = None
    index = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if index % step == 0:
            stats['leidos'] += 1
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            if blur_score(gray) < min_blur:
                stats['borrosos'] += 1
            elif not differs(prev, gray, min_diff):
                stats['repetidos'] += 1
            else:
                prev = cv2.resize(gray, (64, 64))
                h, w = frame.shape[:2]
                if max(h, w) > max_side:
                    scale = max_side / max(h, w)
                    frame = cv2.resize(frame, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA)
                cv2.imwrite(str(out / f'{video.stem}_t{index / fps:07.1f}.jpg'), frame, [cv2.IMWRITE_JPEG_QUALITY, 92])
                stats['guardados'] += 1
        index += 1
    cap.release()
    return stats


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('videos', nargs='+', type=Path, help='videos o carpetas con videos')
    ap.add_argument('--out', type=Path, default=Path('data/bogota/frames'))
    ap.add_argument('--every', type=float, default=1.0, help='segundos entre fotogramas (por defecto 1)')
    ap.add_argument('--min-blur', type=float, default=40.0, help='descarta fotogramas con varianza Laplaciana menor')
    ap.add_argument('--min-diff', type=float, default=4.0, help='descarta fotogramas casi iguales al anterior (0-255)')
    ap.add_argument('--max-side', type=int, default=1280, help='lado mayor máximo en píxeles')
    args = ap.parse_args()

    files = []
    for p in args.videos:
        files += sorted(f for f in p.iterdir() if f.suffix.lower() in VIDEO_EXT) if p.is_dir() else [p]
    if not files:
        raise SystemExit('No encontré videos.')
    for video in files:
        s = extract(video, args.out, args.every, args.min_blur, args.min_diff, args.max_side)
        print(f'{video.name}: {s["guardados"]} guardados de {s["leidos"]} '
              f'({s["borrosos"]} borrosos, {s["repetidos"]} repetidos) -> {args.out}')


if __name__ == '__main__':
    main()
