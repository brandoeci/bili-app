from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.skipif(shutil.which('node') is None, reason='Node.js no está instalado')
def test_seguimiento_de_ruta_en_javascript():
    """web/nav.js corre en el teléfono; sus pruebas están en tests/js/."""
    r = subprocess.run(['node', '--test', 'tests/js/nav.test.js', 'tests/js/voice.test.js', 'tests/js/conexion.test.js', 'tests/js/voz.test.js'], cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-1000:]
