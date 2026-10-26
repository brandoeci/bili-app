from __future__ import annotations

import importlib.util
import itertools
import multiprocessing as mp
import os
import queue
import tempfile
import threading
import time
from pathlib import Path


class VLMUnavailable(RuntimeError):
    """El VLM no puede atender ahora (cargando, ocupado o caído). Falla rápido
    para que el planificador pase al siguiente proveedor sin esperar."""


def _worker_loop(requests: mp.Queue, responses: mp.Queue, model_name: str) -> None:
    try:
        from mlx_vlm import generate, load
        from mlx_vlm.prompt_utils import apply_chat_template

        model, processor = load(model_name)
        _warmup(model, processor, generate, apply_chat_template)
        responses.put({'type': 'ready'})
    except Exception as exc:
        responses.put({'type': 'error', 'error': f'{type(exc).__name__}: {exc}'})
        return

    parent = os.getppid()
    while True:
        try:
            request = requests.get(timeout=2.0)
        except queue.Empty:
            if os.getppid() != parent:  # el servidor murió: no dejar el modelo en memoria
                return
            continue
        if request is None:
            return
        request_id, image_bytes, prompt, max_tokens = request
        image_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as image_file:
                image_file.write(image_bytes)
                image_path = image_file.name
            formatted = apply_chat_template(processor, model.config, prompt, num_images=1)
            output = generate(
                model, processor, formatted, image_path,
                max_tokens=max_tokens, temperature=0.0, verbose=False,
            )
            responses.put({'type': 'result', 'id': request_id, 'text': output.text.strip()})
        except Exception as exc:
            responses.put({'type': 'error', 'id': request_id, 'error': f'{type(exc).__name__}: {exc}'})
        finally:
            if image_path:
                Path(image_path).unlink(missing_ok=True)


def _warmup(model, processor, generate, apply_chat_template) -> None:
    """Primera inferencia con una imagen mínima para compilar kernels y que la
    primera petición real no pague ese coste."""
    import cv2
    import numpy as np

    ok, buf = cv2.imencode('.jpg', np.zeros((64, 64, 3), dtype=np.uint8))
    with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as f:
        f.write(buf.tobytes())
        path = f.name
    try:
        prompt = apply_chat_template(processor, model.config, 'Describe.', num_images=1)
        generate(model, processor, prompt, path, max_tokens=2, temperature=0.0, verbose=False)
    finally:
        Path(path).unlink(missing_ok=True)


class VLMWorker:
    _STALE_RESTART_S = 90.0

    def __init__(self, model_name: str = 'mlx-community/Qwen2.5-VL-3B-Instruct-4bit'):
        self.model_name = model_name
        self.process: mp.Process | None = None
        self.requests: mp.Queue | None = None
        self.responses: mp.Queue | None = None
        self.error: str | None = None
        self.ready = False
        self._request_lock = threading.Lock()
        self._ids = itertools.count(1)
        self._abandoned: dict[int, float] = {}  # peticiones que expiraron y aún pueden responder

    def start(self) -> None:
        if self.process and self.process.is_alive():
            return
        if importlib.util.find_spec('mlx_vlm') is None:
            self.error = 'mlx-vlm no está instalado; ejecuta: pip install mlx-vlm'
            return
        context = mp.get_context('spawn')
        self.ready = False
        self.error = None
        self._abandoned.clear()
        self.requests = context.Queue(maxsize=1)
        self.responses = context.Queue(maxsize=4)
        self.process = context.Process(
            target=_worker_loop, args=(self.requests, self.responses, self.model_name), daemon=True,
        )
        self.process.start()

    def _drain(self, timeout: float = 0.0) -> dict | None:
        """Lee un mensaje; procesa 'ready'/'error' de carga y descarta respuestas caducadas."""
        if not self.responses:
            return None
        try:
            message = self.responses.get(timeout=timeout) if timeout else self.responses.get_nowait()
        except queue.Empty:
            return None
        kind = message.get('type')
        if kind == 'ready':
            self.ready, self.error = True, None
            return None
        if message.get('id') in self._abandoned:
            self._abandoned.pop(message['id'], None)
            return None
        if kind == 'error' and 'id' not in message:
            self.error = message['error']
            return None
        return message

    def describe(self, image_bytes: bytes, prompt: str, timeout: float = 15.0, max_tokens: int = 96) -> str:
        with self._request_lock:
            while self._drain() is not None:
                pass
            if not self.process or not self.process.is_alive():
                raise VLMUnavailable(self.error or 'El proceso VLM local no está disponible')
            if not self.ready:
                raise VLMUnavailable(self.error or 'El VLM local todavía está cargando')
            if self._abandoned:
                oldest = min(self._abandoned.values())
                if time.monotonic() - oldest > self._STALE_RESTART_S:
                    self._restart()
                raise VLMUnavailable('El VLM local sigue ocupado con una petición anterior')

            request_id = next(self._ids)
            try:
                self.requests.put((request_id, image_bytes, prompt, max_tokens), timeout=1)
            except queue.Full as exc:
                raise VLMUnavailable('El VLM local está ocupado') from exc

            deadline = time.monotonic() + timeout
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._abandoned[request_id] = time.monotonic()
                    raise TimeoutError('El VLM local excedió el tiempo de espera')
                message = self._drain(timeout=min(remaining, 0.5))
                if message is None:
                    if not self.process.is_alive():
                        raise VLMUnavailable('El proceso VLM terminó inesperadamente')
                    continue
                if message.get('id') != request_id:
                    continue
                if message['type'] == 'error':
                    raise RuntimeError(message['error'])
                return message['text']

    def _restart(self) -> None:
        self.stop()
        self.start()

    def ping(self) -> str:
        self._drain()
        return 'local-vlm-ready' if self.ready and self.process and self.process.is_alive() else 'local-vlm-unavailable'

    def status(self) -> dict[str, object]:
        if not self._request_lock.locked():
            self._drain()
        alive = self.process is not None and self.process.is_alive()
        if self.process is not None and not alive and not self.ready and self.error is None:
            self.error = f'El proceso VLM terminó con código {self.process.exitcode}'
        return {
            'ready': self.ready and alive,
            'loading': alive and not self.ready and self.error is None,
            'alive': alive,
            'model': self.model_name,
            'error': None if self.ready else self.error,
        }

    def stop(self) -> None:
        if self.process and self.process.is_alive():
            if self.requests:
                try:
                    self.requests.put_nowait(None)
                except queue.Full:
                    pass
            self.process.terminate()
            self.process.join(timeout=1.0)
        self.ready = False
