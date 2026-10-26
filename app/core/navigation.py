from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from statistics import median

import cv2
import numpy as np

SECTORS = {'left': (0.0, 0.33), 'center': (0.33, 0.67), 'right': (0.67, 1.0)}
SIDE_ES = {'left': 'la izquierda', 'center': 'el frente', 'right': 'la derecha'}

_ANALYSIS_W = 128
_FLOOR_ROWS = (0.68, 0.97)       # franja inferior donde se ajusta el plano del suelo
_FLOOR_COLS = (0.10, 0.90)       # ancho casi completo: la mediana por fila ignora un obstáculo central
_MIN_FLOOR_CHANGE = 0.15         # variación relativa mínima de disparidad para aceptar un suelo
_RAISED = 1.35                   # disparidad / suelo esperado: más cerca que el suelo
_SUNKEN = 0.65                   # más lejos que el suelo: hueco o bajada
_MAX_OBSTACLE_RANGE = 4.0        # sin suelo visible, algo más cerca que esto bloquea
_FAR_M = 8.0
_BLOCKED_M = 1.5
_CAUTION_M = 3.0
_PERSISTENCE = {'wall': (2, 3), 'obstacle': (2, 3)}  # (apariciones, ventana); resto 3 de 5
_DEFAULT_PERSISTENCE = (3, 5)


@dataclass
class Hazard:
    kind: str                       # wall | obstacle | drop | stairs_down | stairs_up | step_up
    direction: str                  # left | center | right
    distance_m: float
    bbox_norm: tuple[float, float, float, float]
    note: str | None = None


@dataclass
class PathAnalysis:
    sectors: dict[str, dict] = field(default_factory=dict)
    hazards: list[Hazard] = field(default_factory=list)
    suggestion: str | None = None
    floor_ok: bool = False

    def as_dict(self) -> dict:
        return {
            'sectors': self.sectors,
            'suggestion': self.suggestion,
            'floor_ok': self.floor_ok,
            'hazards': [
                {'kind': h.kind, 'direction': h.direction, 'distance_m': round(h.distance_m, 2)}
                for h in self.hazards
            ],
        }


def hazard_priority(kind: str, direction: str, distance_m: float) -> str:
    if direction != 'center':
        return 'P1' if distance_m < 0.7 else 'P3' if kind in {'wall', 'obstacle'} else (
            'P1' if distance_m < 2.0 else 'P2' if distance_m < 4.0 else 'P3')
    if kind in {'drop', 'stairs_down'}:
        return 'P0' if distance_m < 3.0 else 'P1' if distance_m < 5.0 else 'P2'
    if kind in {'stairs_up', 'step_up'}:
        return 'P0' if distance_m < 2.0 else 'P1' if distance_m < 4.0 else 'P2'
    return 'P0' if distance_m < 1.0 else 'P1' if distance_m < 2.0 else 'P2' if distance_m < 3.5 else 'P3'


class PathAnalyzer:
    """Interpreta un mapa de profundidad métrica para decir *por dónde no se puede
    ir*: paredes, obstáculos sin clase (incluso muy cerca, donde YOLO falla) y
    cambios en el suelo (escalones, escaleras, desniveles).

    Ajusta el plano del suelo en la franja inferior y compara cada píxel con la
    disparidad (1/profundidad) esperada para un suelo plano:
      · mucho más cerca que el suelo → obstáculo / pared / escalón arriba
      · mucho más lejos que el suelo → hueco / bajada / escaleras abajo
    Es experimental: requiere persistencia temporal y validación en campo."""

    def __init__(self) -> None:
        self._history: deque[dict[tuple[str, str], Hazard]] = deque(maxlen=5)

    # ------------------------------------------------------------------ API
    def analyze(self, depth: np.ndarray) -> PathAnalysis:
        depth = self._prepare(depth)
        disp = 1.0 / depth
        h, w = disp.shape

        fit = self._fit_floor(disp)
        floor_ok = fit is not None
        if floor_ok:
            a, b = fit
            ys = np.arange(h, dtype=np.float32)
            d_floor = a * ys + b
        else:
            d_floor = np.zeros(h, dtype=np.float32)

        raw: dict[tuple[str, str], Hazard] = {}
        clearance: dict[str, float] = {}
        for name, (c0f, c1f) in SECTORS.items():
            c0, c1 = int(c0f * w), max(int(c0f * w) + 1, int(c1f * w))
            hazards, clear = self._analyze_sector(name, disp, depth, d_floor, floor_ok, c0, c1)
            clearance[name] = clear
            for hz in hazards:
                raw[(hz.kind, hz.direction)] = hz

        self._history.append(raw)
        stable = self._stable_hazards()
        # Un desnivel a la vista reduce el paso libre de ese sector.
        for hz in stable:
            if hz.kind in {'drop', 'stairs_down'}:
                clearance[hz.direction] = min(clearance[hz.direction], hz.distance_m)

        sectors = {
            name: {'clear_m': round(min(c, _FAR_M), 1), 'state': self._state(c)}
            for name, c in clearance.items()
        }
        suggestion = self._suggest(sectors)
        for hz in stable:
            if hz.direction == 'center':
                hz.note = self._note(sectors, suggestion)
        stable.sort(key=lambda hz: hz.distance_m)
        return PathAnalysis(sectors=sectors, hazards=stable, suggestion=suggestion, floor_ok=floor_ok)

    def reset(self) -> None:
        self._history.clear()

    # ------------------------------------------------------------ internals
    @staticmethod
    def _prepare(depth: np.ndarray) -> np.ndarray:
        h, w = depth.shape[:2]
        small = cv2.resize(depth.astype(np.float32), (_ANALYSIS_W, max(8, round(_ANALYSIS_W * h / w))),
                           interpolation=cv2.INTER_AREA)
        return np.clip(small, 0.2, 30.0)

    @staticmethod
    def _fit_floor(disp: np.ndarray) -> tuple[float, float] | None:
        h, w = disp.shape
        r0, r1 = int(_FLOOR_ROWS[0] * h), int(_FLOOR_ROWS[1] * h)
        c0, c1 = int(_FLOOR_COLS[0] * w), int(_FLOOR_COLS[1] * w)
        ys = np.arange(r0, r1, dtype=np.float32)
        vals = np.median(disp[r0:r1, c0:c1], axis=1)
        keep = np.ones_like(ys, dtype=bool)
        a = b = 0.0
        for _ in range(3):  # ajuste robusto: descarta objetos que se cuelan en la franja
            if keep.sum() < 4:
                return None
            a, b = np.polyfit(ys[keep], vals[keep], 1)
            res = vals - (a * ys + b)
            mad = np.median(np.abs(res[keep])) + 1e-4
            keep = np.abs(res) < 3.0 * mad + 0.02 * float(np.mean(vals))
        mean = float(np.mean(vals[keep]))
        change = a * (r1 - r0) / max(mean, 1e-6)
        rms = float(np.sqrt(np.mean((vals[keep] - (a * ys[keep] + b)) ** 2))) / max(mean, 1e-6)
        if a <= 0 or change < _MIN_FLOOR_CHANGE or rms > 0.15 or keep.sum() < 0.5 * len(ys):
            return None  # el suelo no se ve (p. ej. de frente a una pared)
        return float(a), float(b)

    def _analyze_sector(self, name, disp, depth, d_floor, floor_ok, c0, c1):
        h, w = disp.shape
        inner0 = c0 + (c1 - c0) // 10
        inner1 = c1 - (c1 - c0) // 10
        top, bottom = int(0.15 * h), int(0.97 * h)
        hazards: list[Hazard] = []
        x_norm = (c0 / w, c1 / w)

        horizon = d_floor > 0.125  # filas donde el suelo estaría a menos de 8 m
        if floor_ok:
            ratio = disp / np.where(d_floor[:, None] > 0.05, d_floor[:, None], np.nan)
            obstacle = np.where(np.isnan(ratio), depth < _MAX_OBSTACLE_RANGE, ratio > _RAISED)
        else:
            obstacle = depth < _MAX_OBSTACLE_RANGE
            ratio = None
        band = np.zeros_like(obstacle)
        band[top:bottom, c0:c1] = True
        mask = obstacle & band

        floor_hazard_dist: float | None = None
        if floor_ok:
            floor_hazard_dist = self._floor_changes(
                name, disp, ratio, d_floor, horizon, inner0, inner1, x_norm, hazards)

        clear = _FAR_M * 4
        area = (bottom - top) * (c1 - c0)
        if mask.sum() >= max(6, 0.03 * area):
            obs_depth = depth[mask]
            clear = float(np.percentile(obs_depth, 10))
            coverage = float(mask.sum()) / area
            obs_disp = disp[mask]
            uniform = float(np.std(obs_disp)) / max(float(np.mean(obs_disp)), 1e-6) < 0.15
            rows = np.where(mask.any(axis=1))[0]
            bbox = (x_norm[0], rows.min() / h, x_norm[1], (rows.max() + 1) / h)
            closer_than_floor_hazard = floor_hazard_dist is None or clear < floor_hazard_dist - 0.5
            if closer_than_floor_hazard:
                if coverage >= 0.45 and uniform:
                    hazards.append(Hazard('wall', name, clear, bbox))
                elif clear < _MAX_OBSTACLE_RANGE:
                    hazards.append(Hazard('obstacle', name, clear, bbox))
        return hazards, clear

    def _floor_changes(self, name, disp, ratio, d_floor, horizon, c0, c1, x_norm, hazards):
        """Busca escalones, escaleras y desniveles recorriendo el perfil vertical del sector."""
        h = disp.shape[0]
        rows = np.where(horizon)[0]
        if len(rows) < 8:
            return None
        y_top, y_bot = int(rows.min()), int(0.97 * h)
        prof = np.nanmedian(ratio[y_top:y_bot, c0:c1], axis=1)
        dprof = np.median(disp[y_top:y_bot, c0:c1], axis=1)
        ys = np.arange(y_top, y_bot)
        min_run = max(3, int(0.04 * h))

        def runs(cond):
            out, start = [], None
            for i, flag in enumerate(cond):
                if flag and start is None:
                    start = i
                elif not flag and start is not None:
                    out.append((start, i - 1))
                    start = None
            if start is not None:
                out.append((start, len(cond) - 1))
            return [r for r in out if r[1] - r[0] + 1 >= min_run]

        def edge_distance(run_end_idx: int) -> float:
            y = min(ys[run_end_idx] + 1, h - 1)
            return float(1.0 / max(d_floor[y], 1e-3))

        def jumps(run):
            seg = dprof[run[0]:run[1] + 1]
            if len(seg) < 3:
                return 0
            return int(np.sum(np.abs(np.diff(seg)) / max(float(np.mean(seg)), 1e-6) > 0.18))

        found: float | None = None
        for run in runs(prof < _SUNKEN):
            dist = edge_distance(run[1])
            kind = 'stairs_down' if jumps(run) >= 2 else 'drop'
            hazards.append(Hazard(kind, name, dist, (x_norm[0], ys[run[0]] / h, x_norm[1], (ys[run[1]] + 1) / h)))
            found = dist if found is None else min(found, dist)
            break  # el más cercano basta
        for run in runs(prof > _RAISED):
            seg_y = ys[run[0]:run[1] + 1].astype(np.float32)
            seg_d = dprof[run[0]:run[1] + 1]
            slope = np.polyfit(seg_y, seg_d, 1)[0] / max(float(d_floor[1] - d_floor[0]), 1e-6) if len(seg_y) >= 4 else 1.0
            reaches_top = run[1] >= len(prof) - 2 or run[0] == 0
            height = run[1] - run[0] + 1
            dist = edge_distance(run[1])
            if reaches_top and slope < 0.2 and height > 0.12 * h:
                continue  # superficie vertical: la trata la lógica de pared/obstáculo
            kind = 'stairs_up' if jumps(run) >= 2 and slope > 0.2 else 'step_up'
            if height > 0.12 * h and kind == 'step_up' and slope < 0.2:
                continue
            hazards.append(Hazard(kind, name, dist, (x_norm[0], ys[run[0]] / h, x_norm[1], (ys[run[1]] + 1) / h)))
            found = dist if found is None else min(found, dist)
            break
        return found

    def _stable_hazards(self) -> list[Hazard]:
        out: list[Hazard] = []
        keys = {k for frame in self._history for k in frame}
        for key in keys:
            need, window = _PERSISTENCE.get(key[0], _DEFAULT_PERSISTENCE)
            recent = list(self._history)[-window:]
            hits = [frame[key] for frame in recent if key in frame]
            if len(hits) >= need and key in self._history[-1]:
                latest = self._history[-1][key]
                latest.distance_m = float(median(h.distance_m for h in hits))
                out.append(latest)
        return out

    @staticmethod
    def _state(clear_m: float) -> str:
        return 'blocked' if clear_m < _BLOCKED_M else 'caution' if clear_m < _CAUTION_M else 'free'

    @staticmethod
    def _suggest(sectors: dict[str, dict]) -> str | None:
        if sectors['center']['state'] != 'blocked':
            return None
        side, best = None, 0.0
        for name in ('left', 'right'):
            if sectors[name]['state'] == 'free' and sectors[name]['clear_m'] > best:
                side, best = name, sectors[name]['clear_m']
        return side or 'stop'

    @staticmethod
    def _note(sectors: dict[str, dict], suggestion: str | None) -> str | None:
        parts = []
        for name in ('left', 'right'):
            if sectors[name]['state'] == 'blocked':
                parts.append(f'{"Izquierda" if name == "left" else "Derecha"} bloqueada.')
        if suggestion == 'stop':
            parts.append('No hay paso libre, deténgase.')
        elif suggestion:
            parts.append(f'Libre hacia {SIDE_ES[suggestion]}.')
        return ' '.join(parts) or None
