from __future__ import annotations

from pathlib import Path


def main() -> None:
    from ultralytics import YOLO

    models_dir = Path(__file__).resolve().parent.parent / 'models'
    models_dir.mkdir(exist_ok=True)
    for model_name in ('yolo26s.pt', 'yolo11n.pt'):
        YOLO(str(models_dir / model_name))
        print(f'Descargado: {models_dir / model_name}')
    print('Para exportar CoreML en macOS, usa un entorno con coremltools instalado.')


if __name__ == '__main__':
    main()
