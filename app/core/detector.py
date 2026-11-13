from __future__ import annotations

from pathlib import Path

import numpy as np

from app.schemas import Detection

try:
    from ultralytics import YOLO
except ImportError:  # pragma: no cover - allows API startup with optional detector dependency absent
    YOLO = None


class YoloDetector:
    def __init__(
        self,
        model_path: str = 'models/yolo26s.pt',
        conf: float = 0.35,
        iou: float = 0.5,
        classes: list[str] | None = None,
        device: str | None = None,
        id_offset: int = 0,
        class_conf: dict[str, float] | None = None,
    ):
        self.conf = conf
        # Umbrales por clase, más estrictos que `conf` (p. ej. escaleras: en calles de Bogotá la mitad de las alarmas a 0.35 eran falsas).
        # Solo pueden subir el umbral: el modelo ya descarta todo lo que esté por debajo de `conf`.
        self.class_conf = {k.lower(): float(v) for k, v in (class_conf or {}).items()}
        # Con dos detectores, cada tracker numera desde 1: el offset evita que los IDs se mezclen en la fusión.
        self.id_offset = id_offset
        self.iou = iou
        # None significa todas las clases COCO. El filtrado opcional se aplica
        # solamente cuando el usuario configura una lista explícita.
        self.classes = set(classes) if classes else None
        self._track_counter = 0
        self.device = device or self._default_device()
        self._shape: tuple[int, ...] | None = None
        self.model_path = Path(model_path)
        self.model = None
        self.error: str | None = None
        if YOLO is None:
            self.error = 'ultralytics no está instalado'
        elif not self.model_path.exists():
            self.error = f'No existe el modelo YOLO: {self.model_path}'
        else:
            try:
                self.model = YOLO(str(self.model_path))
            except Exception as exc:
                self.error = f'{type(exc).__name__}: {exc}'

    @staticmethod
    def _default_device() -> str | None:
        try:
            import torch
            return 'mps' if torch.backends.mps.is_available() else None
        except ImportError:  # pragma: no cover
            return None

    def reset(self) -> None:
        """Descarta el estado del tracker (IDs y frame previo para compensación de movimiento)."""
        self._shape = None
        predictor = getattr(self.model, 'predictor', None)
        for tracker in getattr(predictor, 'trackers', None) or []:
            tracker.reset()

    def track(self, frame: np.ndarray) -> list[Detection]:
        if frame is None or frame.size == 0:
            return []
        if self.model is None:
            return []

        h, w = frame.shape[:2]
        # El GMC del tracker compara con el frame previo: si cambia el tamaño, falla. Reiniciar.
        if self._shape is not None and self._shape != frame.shape:
            self.reset()
        self._shape = frame.shape
        detections: list[Detection] = []
        results = self.model.track(
            source=frame,
            conf=self.conf,
            iou=self.iou,
            persist=True,
            device=self.device,
            verbose=False,
        )
        if not results:
            return detections
        result = results[0]
        names = result.names
        boxes = result.boxes
        for index in range(len(boxes)):
            class_id = int(boxes.cls[index].item())
            label = str(names[class_id]).lower()
            if self.classes is not None and label not in self.classes:
                continue
            confidence = float(boxes.conf[index].item())
            if confidence < self.class_conf.get(label, 0.0):
                continue
            x1, y1, x2, y2 = [int(value) for value in boxes.xyxy[index].tolist()]
            track_id = None
            if boxes.id is not None:
                track_id = int(boxes.id[index].item()) + self.id_offset
            detections.append(
                Detection(
                    track_id=track_id,
                    label=label,
                    conf=confidence,
                    bbox=(max(0, x1), max(0, y1), min(w, x2), min(h, y2)),
                )
            )

        return detections
