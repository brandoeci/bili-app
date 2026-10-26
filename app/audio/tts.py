from __future__ import annotations

import itertools
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from queue import PriorityQueue

_RANK = {'P0': 0, 'P1': 1, 'P2': 2, 'P3': 3}
# Una alerta que espera más de esto ya describe una situación pasada: se descarta.
_MAX_AGE_S = {'P0': 4.0, 'P1': 4.0, 'P2': 20.0, 'P3': 10.0}
_DEDUP_WINDOW_S = 6.0


@dataclass(order=True)
class SpeechItem:
    rank: int
    seq: int
    text: str = field(compare=False, default='')
    priority: str = field(compare=False, default='P3')
    created: float = field(compare=False, default=0.0)
    stop: bool = field(compare=False, default=False)
    interruptible: bool = field(compare=False, default=True)


class Speaker:
    """Cola de voz con prioridad.

    - P0 interrumpe lo que se esté diciendo y descarta lo de menor prioridad.
    - Una descripción de escena (P2) reemplaza a otra P2 pendiente (latest-wins).
    - Mensajes repetidos en una ventana corta y mensajes caducados se omiten.
    """

    def __init__(self, voice: str = 'Soledad', rate: int = 190):
        self.voice = voice
        self.rate = rate
        self.proc: subprocess.Popen | None = None
        self._queue: PriorityQueue[SpeechItem] = PriorityQueue()
        self._lock = threading.Lock()
        self._seq = itertools.count()
        self._stopped = False
        self._recent: dict[str, float] = {}
        self._current_rank = 99
        self._current_interruptible = True
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()

    def _command(self, text: str) -> list[str] | None:
        """Elige el motor de voz de la plataforma: say (macOS), espeak-ng/espeak (Linux)."""
        if shutil.which('say'):
            return ['say', '-v', self.voice, '-r', str(self.rate), text]
        for engine in ('espeak-ng', 'espeak'):
            if shutil.which(engine):
                return [engine, '-v', 'es', '-s', str(self.rate), text]
        return None

    def say(self, text: str, priority: str = 'P3', force: bool = False, interruptible: bool = True) -> bool:
        text = (text or '').strip()
        if not text or self._command(text) is None:
            return False
        rank = _RANK.get(priority, 3)
        now = time.monotonic()
        key = ' '.join(text.casefold().split())

        with self._lock:
            if self._stopped:
                return False
            if not force and now - self._recent.get(key, -1e9) < _DEDUP_WINDOW_S:
                return False
            self._recent[key] = now
            self._recent = {k: t for k, t in self._recent.items() if now - t < _DEDUP_WINDOW_S}
            if rank == 0:
                self._drop_pending(lambda item: item.rank > 0)
                if self.proc is not None and self._current_rank > 0 and self._current_interruptible:
                    self.proc.terminate()
            elif rank == 2:
                self._drop_pending(lambda item: item.rank == 2)
            self._queue.put(SpeechItem(rank, next(self._seq), text, priority, now, interruptible=interruptible))
        return True

    def _drop_pending(self, predicate) -> None:
        kept: list[SpeechItem] = []
        while not self._queue.empty():
            try:
                item = self._queue.get_nowait()
            except Exception:
                break
            if predicate(item) and not item.stop:
                self._queue.task_done()
            else:
                kept.append(item)
                self._queue.task_done()
        for item in kept:
            self._queue.put(item)

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            try:
                if item.stop:
                    return
                if time.monotonic() - item.created > _MAX_AGE_S.get(item.priority, 10.0):
                    continue
                command = self._command(item.text)
                if command is None:
                    continue
                process = subprocess.Popen(
                    command,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                with self._lock:
                    self.proc = process
                    self._current_rank = item.rank
                    self._current_interruptible = item.interruptible
                process.wait()
                with self._lock:
                    self.proc = None
                    self._current_rank = 99
            except OSError:
                with self._lock:
                    self.proc = None
            finally:
                self._queue.task_done()

    def shutdown(self) -> None:
        with self._lock:
            if self._stopped:
                return
            self._stopped = True
            self._queue.put(SpeechItem(-1, next(self._seq), stop=True))
        self._worker.join(timeout=2.0)
