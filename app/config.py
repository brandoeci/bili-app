from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parent.parent / '.env',
        env_file_encoding='utf-8',
        case_sensitive=False,
        extra='ignore',
    )

    app_name: str = 'Vision Asistiva'
    api_version: str = 'v1'
    host: str = '127.0.0.1'
    port: int = 8000
    workers: int = 1

    camera_source: str = 'remote'  # remote: frames del celular por /ws/frames | local: webcam del servidor
    audio_output: str = 'client'  # client: habla el celular | server: habla el servidor (say/espeak) | both
    camera_index: int = 0
    camera_width: int = 1280
    camera_height: int = 720
    camera_fps: int = 30
    process_size: int = 640
    camera_focal_ratio: float = 0.8  # focal/ancho; calibrar con POST /v1/calibrate

    detector_model: str = 'models/yolo26s.pt'
    detector_conf: float = 0.35
    detector_iou: float = 0.5
    detector_device: str | None = None  # None: mps si existe, si no ultralytics decide
    detector_classes: list[str] | None = None
    # Segundo detector, entrenado por nosotros (scripts/dataset/train.py). Si el archivo no existe, se omite.
    hazard_model: str = 'models/bili-hazards.pt'
    hazard_conf: float = 0.35

    depth_enabled: bool = True
    depth_model: str = 'depth-anything/Depth-Anything-V2-Metric-Indoor-Small-hf'  # Outdoor-Small-hf para exteriores
    depth_every_n_frames: int = 3
    depth_input_px: int = 392  # lado corto de entrada; 518 = nativo (más lento)

    alerts_critical_distance_m: float = 2.5
    alerts_release_distance_m: float = 3.2
    alerts_cooldown_s: float = 5.0
    alerts_reminder_s: float = 12.0
    alerts_min_frames: int = 2
    alerts_max_speech_rate_s: float = 1.5

    audio_voice: str = 'Mónica'
    audio_rate_wpm: int = 190
    audio_earcons: bool = True
    audio_verbosity: str = 'normal'  # normal | quiet (sólo peligros P0)
    debug_endpoints: bool = True

    scene_mode: str = 'auto'
    scene_auto_interval_s: int = 20
    scene_heuristic_interval_s: int = 60
    scene_vlm_model: str = 'mlx-community/Qwen2.5-VL-3B-Instruct-4bit'
    scene_vlm_max_side_px: int = 512
    scene_vlm_enabled: bool = True
    scene_local_timeout_s: float = 15.0
    scene_cache_ttl_s: float = 5.0
    scene_min_gap_s: float = 8.0
    scene_max_silence_s: float = 45.0
    scene_poll_s: float = 2.0
    scene_gemini_max_side_px: int = 640

    gemini_api_key: str = ''
    gemini_model: str = 'gemini-3.6-flash'
    gemini_timeout_s: float = 20.0

    base_dir: Path = Path(__file__).resolve().parent.parent

    @property
    def web_dir(self) -> Path:
        return self.base_dir / 'web'


settings = Settings()
