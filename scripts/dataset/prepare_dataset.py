"""Une varios datasets en formato YOLO en uno solo con las clases de peligros de Bili.

COCO no trae huecos, bordillos ni escaleras. Cada dataset público nombra distinto esas clases, así que
aquí se llevan a un conjunto único (`BILI_CLASSES`) por reglas de nombre; todo lo demás se descarta
(personas y vehículos ya los cubre el detector COCO).

Uso:
    # 1) ver qué clases trae cada fuente y a cuál se mapearía (no escribe nada)
    python scripts/dataset/prepare_dataset.py --list data/raw/sod data/raw/pothole-stair

    # 2) construir el dataset unificado
    python scripts/dataset/prepare_dataset.py data/raw/sod data/raw/pothole-stair data/raw/bogota --out data/bili-dataset

Cada fuente es una carpeta en formato YOLO (la que exporta Roboflow como "YOLOv8"): data.yaml y
train|valid|test/{images,labels}. Las etiquetas de segmentación (polígonos) se convierten a cajas.
"""
from __future__ import annotations

import argparse
import random
import shutil
import sys
from collections import Counter
from pathlib import Path

import yaml

# El orden define el id de clase del modelo. 'stairs' = escalera sin dirección conocida.
BILI_CLASSES = ['pothole', 'manhole', 'curb', 'stairs_down', 'stairs_up', 'stairs', 'pole', 'obstacle']

# Se evalúa en orden; gana la primera regla que coincida. Cada regla: (palabras que deben aparecer, clase).
RULES: list[tuple[tuple[str, ...], str]] = [
    (('manhole',), 'manhole'), (('sewer',), 'manhole'), (('drain',), 'manhole'), (('cover',), 'manhole'),
    (('pothole',), 'pothole'), (('hole',), 'pothole'), (('bache',), 'pothole'),
    (('stair', 'down'), 'stairs_down'), (('downstair',), 'stairs_down'), (('descend',), 'stairs_down'),
    (('stair', 'up'), 'stairs_up'), (('upstair',), 'stairs_up'), (('ascend',), 'stairs_up'),
    (('stair',), 'stairs'), (('step',), 'stairs'), (('escalera',), 'stairs'),
    (('curb',), 'curb'), (('kerb',), 'curb'), (('bordillo',), 'curb'),
    (('pole',), 'pole'), (('post',), 'pole'), (('bollard',), 'pole'), (('poste',), 'pole'),
    (('street', 'light'), 'pole'),
    (('obstacle',), 'obstacle'), (('barrier',), 'obstacle'), (('cone',), 'obstacle'),
    (('roadblock',), 'obstacle'), (('warning',), 'obstacle'), (('waste',), 'obstacle'),
]
SPLITS = {'train': 'train', 'valid': 'val', 'val': 'val', 'test': 'test'}
IMG_EXT = {'.jpg', '.jpeg', '.png', '.bmp', '.webp'}


def map_name(name: str) -> str | None:
    n = name.lower().replace('_', ' ').replace('-', ' ')
    for words, target in RULES:
        if all(w in n for w in words):
            return target
    return None


def read_names(src: Path) -> list[str]:
    cfg = yaml.safe_load((src / 'data.yaml').read_text(encoding='utf-8'))
    names = cfg['names']
    return [names[i] for i in sorted(names)] if isinstance(names, dict) else list(names)


def to_bbox(parts: list[str]) -> tuple[float, float, float, float] | None:
    """Línea YOLO -> (cx, cy, w, h). Acepta caja (5 valores) o polígono (2n+1 valores)."""
    try:
        vals = [float(p) for p in parts[1:]]
    except ValueError:
        return None
    if len(vals) == 4:
        return tuple(vals)  # type: ignore[return-value]
    if len(vals) >= 6 and len(vals) % 2 == 0:
        xs, ys = vals[0::2], vals[1::2]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        return ((x0 + x1) / 2, (y0 + y1) / 2, x1 - x0, y1 - y0)
    return None


def list_sources(sources: list[Path]) -> None:
    for src in sources:
        print(f'\n{src}')
        for i, name in enumerate(read_names(src)):
            print(f'  {i:>2}  {name:<28} -> {map_name(name) or "(se descarta)"}')


def build(sources: list[Path], out: Path, neg_ratio: float, seed: int) -> None:
    rng = random.Random(seed)
    if out.exists():
        shutil.rmtree(out)
    for split in ('train', 'val', 'test'):
        (out / 'images' / split).mkdir(parents=True)
        (out / 'labels' / split).mkdir(parents=True)

    class_id = {c: i for i, c in enumerate(BILI_CLASSES)}
    counts: dict[str, Counter] = {}
    unmapped: Counter = Counter()
    images_kept = Counter()

    for src in sources:
        names = read_names(src)
        remap = {i: class_id[t] for i, n in enumerate(names) if (t := map_name(n))}
        counts[src.name] = Counter()
        for raw_split, split in SPLITS.items():
            img_dir, lbl_dir = src / raw_split / 'images', src / raw_split / 'labels'
            if not img_dir.is_dir():
                continue
            positives, negatives = [], []
            for img in sorted(p for p in img_dir.iterdir() if p.suffix.lower() in IMG_EXT):
                lines = []
                lbl = lbl_dir / (img.stem + '.txt')
                if lbl.exists():
                    for line in lbl.read_text().splitlines():
                        parts = line.split()
                        if not parts:
                            continue
                        old = int(float(parts[0]))
                        box = to_bbox(parts)
                        if box is None:
                            continue
                        if old in remap:
                            lines.append((remap[old], box))
                        else:
                            unmapped[names[old] if old < len(names) else str(old)] += 1
                (positives if lines else negatives).append((img, lines))
            # Fondos sin ninguna clase útil: se conserva una fracción para que el modelo aprenda a no inventar peligros.
            rng.shuffle(negatives)
            chosen = positives + negatives[: int(len(positives) * neg_ratio)]
            for img, lines in chosen:
                stem = f'{src.name}_{raw_split}_{img.stem}'
                shutil.copy2(img, out / 'images' / split / f'{stem}{img.suffix.lower()}')
                body = '\n'.join(
                    f'{cid} {min(max(v, 0.0), 1.0):.6f} {min(max(c, 0.0), 1.0):.6f} {min(max(w, 0.0), 1.0):.6f} {min(max(h, 0.0), 1.0):.6f}'
                    for cid, (v, c, w, h) in lines
                )
                (out / 'labels' / split / f'{stem}.txt').write_text(body + ('\n' if body else ''))
                images_kept[split] += 1
                for cid, _ in lines:
                    counts[src.name][BILI_CLASSES[cid]] += 1

    (out / 'data.yaml').write_text(yaml.safe_dump({
        'train': 'images/train', 'val': 'images/val', 'test': 'images/test',
        'names': {i: c for i, c in enumerate(BILI_CLASSES)},
    }, allow_unicode=True, sort_keys=False), encoding='utf-8')

    print(f'\nDataset en {out}  ·  imágenes: {dict(images_kept)}')
    total = Counter()
    for name, c in counts.items():
        total.update(c)
        print(f'  {name}: {dict(c)}')
    print('\nInstancias por clase (todas las fuentes):')
    for c in BILI_CLASSES:
        flag = '   <-- POCAS, conseguir más datos' if total[c] < 300 else ''
        print(f'  {c:<12} {total[c]:>7}{flag}')
    if unmapped:
        print('\nDescartadas (sin regla de mapeo):', dict(unmapped.most_common(15)))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('sources', nargs='+', type=Path)
    ap.add_argument('--out', type=Path, default=Path('data/bili-dataset'))
    ap.add_argument('--list', action='store_true', help='solo mostrar clases y su mapeo')
    ap.add_argument('--neg-ratio', type=float, default=0.1, help='fondos sin objetos a conservar, como fracción de las imágenes con objetos')
    ap.add_argument('--seed', type=int, default=0)
    args = ap.parse_args()
    missing = [s for s in args.sources if not (s / 'data.yaml').exists()]
    if missing:
        sys.exit(f'No encuentro data.yaml en: {", ".join(map(str, missing))}')
    list_sources(args.sources) if args.list else build(args.sources, args.out, args.neg_ratio, args.seed)


if __name__ == '__main__':
    main()
