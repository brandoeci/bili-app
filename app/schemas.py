from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Detection(BaseModel):
    track_id: int | None = None
    label: str = 'person'
    conf: float = 0.0
    bbox: tuple[int, int, int, int] = (0, 0, 0, 0)
    direction: Literal['left', 'center', 'right'] = 'center'
    clock: int = 12
    distance_m: float | None = None
    approach_speed_mps: float | None = None
    ttc_s: float | None = None
    priority: Literal['P0', 'P1', 'P2', 'P3'] = 'P3'
    note: str | None = None  # indicación extra para la alerta (p. ej. 'Libre a su derecha')


class Alert(BaseModel):
    id: str
    ts: float
    priority: Literal['P0', 'P1', 'P2', 'P3']
    text: str
    source: Literal['reflex', 'vlm_local', 'gemini']
    track_id: int | None = None


class FrameEvent(BaseModel):
    ts: float
    fps: float
    latency_ms: dict[str, float]
    detections: list[Detection] = Field(default_factory=list)
    navigation: dict | None = None


class DescribeRequest(BaseModel):
    mode: Literal['local', 'gemini', 'auto'] = 'auto'
    task: Literal['scene', 'read_text', 'ask'] = 'scene'
    question: str | None = None
    speak: bool = True


class DescribeResponse(BaseModel):
    text: str
    source: Literal['vlm_local', 'gemini', 'heuristic']
    latency_ms: float
    degraded: bool = False   # True si ningún modelo respondió y se usó el resumen del detector
    unchanged: bool = False  # True si el modelo indicó que nada relevante cambió
    cached: bool = False
    trace: list[dict] = Field(default_factory=list)  # intentos por proveedor, para depuración


class ConfigUpdate(BaseModel):
    scene_mode: str | None = None
    camera_index: int | None = None
    detector_conf: float | None = None
    audio_voice: str | None = None
    audio_rate_wpm: int | None = Field(default=None, ge=80, le=400)
    audio_verbosity: Literal['normal', 'quiet'] | None = None
