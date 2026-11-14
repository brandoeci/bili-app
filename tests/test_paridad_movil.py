"""El motor del celular (web/bili/*.js) debe decidir y hablar exactamente igual que el servidor (app/core/*.py).

Si alguien cambia un umbral, una frase o una distancia en un lado y no en el otro, esta prueba falla. Necesita Node (se salta si no está)."""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
NODE = shutil.which('node')
pytestmark = pytest.mark.skipif(NODE is None, reason='Node no está instalado')


def test_pruebas_unitarias_de_javascript():
    r = subprocess.run([NODE, '--test', *map(str, sorted((RAIZ / 'tests' / 'js').glob('*.test.mjs')))], capture_output=True, text=True, cwd=RAIZ)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]


def test_motor_de_decision_igual_en_python_y_en_javascript(tmp_path):
    casos = tmp_path / 'motor.json'
    subprocess.run([sys.executable, str(RAIZ / 'scripts' / 'movil' / 'paridad_motor.py'), '--salida', str(casos), '--escenarios', '40'],
                   check=True, capture_output=True, cwd=RAIZ)
    r = subprocess.run([NODE, str(RAIZ / 'scripts' / 'movil' / 'paridad_motor.mjs'), str(casos)], capture_output=True, text=True, cwd=RAIZ)
    assert r.returncode == 0, r.stdout[-3000:]
    assert 'diferencias 0' in r.stdout
