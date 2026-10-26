from __future__ import annotations

import cv2
import numpy as np

from app.core.labels import LABELS_ES
from app.schemas import Detection


def draw_overlay(frame: np.ndarray, detections: list[Detection]) -> np.ndarray:
    out = frame.copy()
    h, w = out.shape[:2]

    # corredor de caminata central
    cv2.rectangle(out, (int(w * 0.3), int(h * 0.65)), (int(w * 0.7), int(h * 0.96)), (0, 180, 255), 2)
    cv2.putText(
        out,
        f'detecciones: {len(detections)}',
        (12, 24),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.65,
        (255, 255, 255),
        2,
    )
    cv2.putText(out, 'corredor', (int(w * 0.42), int(h * 0.62)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 180, 255), 1)

    for det in detections:
        x1, y1, x2, y2 = det.bbox
        color = (0, 0, 255) if det.priority == 'P0' else (0, 140, 255) if det.priority == 'P1' else (0, 200, 200)
        cv2.rectangle(out, (x1, y1), (x2, y2), color, 2)
        label = f"{LABELS_ES.get(det.label, det.label)} {det.conf:.2f}"
        if det.distance_m is not None:
            label += f" · {det.distance_m:.1f} m"
        cv2.putText(out, label, (x1, max(0, y1 - 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)

    return out
