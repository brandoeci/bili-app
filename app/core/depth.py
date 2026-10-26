from __future__ import annotations

import logging
import threading

import cv2
import numpy as np

log = logging.getLogger(__name__)

DEFAULT_MODEL = 'depth-anything/Depth-Anything-V2-Metric-Indoor-Small-hf'


class DepthModel:
    """Profundidad métrica monocular (Depth Anything V2 Metric, en metros).

    Se carga en un hilo para no retrasar el arranque; mientras no esté lista
    ``enabled`` es False y el sistema usa la geometría del bbox. Para exteriores
    usa ``depth-anything/Depth-Anything-V2-Metric-Outdoor-Small-hf``."""

    def __init__(self, enabled: bool = True, model_id: str = DEFAULT_MODEL, input_px: int = 392):
        self.requested = enabled
        self.model_id = model_id
        # Lado corto de entrada (múltiplo de 14). 518 es el nativo del modelo, pero cuesta ~2.3x más.
        self.input_px = max(14, round(input_px / 14) * 14)
        self.model = None
        self.processor = None
        self.device = 'cpu'
        self.error: str | None = None
        self.loading = False
        self._torch = None
        self._on_device = False
        self._half = False
        self._mean = self._std = None

    def start(self) -> None:
        if not self.requested or self.model is not None or self.loading:
            return
        self.loading = True
        threading.Thread(target=self._load, daemon=True).start()

    def _load(self) -> None:
        try:
            import torch
            from transformers import AutoImageProcessor, AutoModelForDepthEstimation

            self._torch = torch
            self.device = 'mps' if torch.backends.mps.is_available() else 'cuda' if torch.cuda.is_available() else 'cpu'
            processor = AutoImageProcessor.from_pretrained(self.model_id)
            # Sólo se descargan los pesos en CPU. Metal (MPS) no es seguro entre hilos: mover a GPU
            # y calentar ocurre en la primera llamada a infer(), desde el hilo del pipeline.
            model = AutoModelForDepthEstimation.from_pretrained(self.model_id).eval()
            self.processor, self.model = processor, model
            log.info('Modelo de profundidad listo (%s en %s)', self.model_id, self.device)
        except Exception as exc:
            self.model = None
            self.error = f'{type(exc).__name__}: {exc}'
            log.warning('Profundidad no disponible: %s', self.error)
        finally:
            self.loading = False

    @property
    def enabled(self) -> bool:
        return self.requested and self.model is not None

    def infer(self, frame_bgr: np.ndarray | None) -> np.ndarray | None:
        """Devuelve un mapa (h', w') en metros con la relación de aspecto del frame."""
        if not self.enabled or frame_bgr is None:
            return None
        torch = self._torch
        if not self._on_device:
            # fp16 en GPU: misma salida que fp32 (diferencia nula medida) y ~20% más rápido.
            self._half = self.device != 'cpu'
            self.model.to(self.device)
            if self._half:
                self.model.half()
            self._mean = np.array(self.processor.image_mean, np.float32)
            self._std = np.array(self.processor.image_std, np.float32)
            self._on_device = True
        h, w = frame_bgr.shape[:2]
        scale = self.input_px / min(h, w)
        size = (max(14, round(w * scale / 14) * 14), max(14, round(h * scale / 14) * 14))
        rgb = cv2.resize(frame_bgr[:, :, ::-1], size, interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR)
        x = (rgb.astype(np.float32) / 255.0 - self._mean) / self._std
        pixels = torch.from_numpy(np.ascontiguousarray(x.transpose(2, 0, 1)))[None].to(self.device)
        if self._half:
            pixels = pixels.half()
        with torch.inference_mode():
            depth = self.model(pixel_values=pixels).predicted_depth
        return depth[0].float().cpu().numpy()

    def status(self) -> dict[str, object]:
        return {'enabled': self.enabled, 'loading': self.loading, 'model': self.model_id,
                'device': self.device, 'error': self.error}
