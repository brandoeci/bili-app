import importlib.util
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location('extraer_cuadros_video', Path(__file__).parent.parent / 'scripts' / 'dataset' / 'extraer_cuadros_video.py')
ev = importlib.util.module_from_spec(spec)
sys.modules['extraer_cuadros_video'] = ev
spec.loader.exec_module(ev)

EX = [(100.0, 145.0), (300.0, 345.0)]


def test_dentro_de_un_tramo_de_examen_es_examen():
    assert ev.tramo(100, EX, 10) == 'examen' and ev.tramo(144.9, EX, 10) == 'examen' and ev.tramo(320, EX, 10) == 'examen'


def test_el_margen_a_cada_lado_es_buffer_y_el_borde_final_es_exclusivo():
    assert ev.tramo(90, EX, 10) == 'buffer' and ev.tramo(99.9, EX, 10) == 'buffer'
    assert ev.tramo(145, EX, 10) == 'buffer' and ev.tramo(154.9, EX, 10) == 'buffer'
    assert ev.tramo(155, EX, 10) == 'train' and ev.tramo(89.9, EX, 10) == 'train'


def test_sin_tramos_de_examen_todo_es_train():
    assert ev.tramo(50, [], 10) == 'train'


def test_ningun_segundo_queda_a_la_vez_en_dos_grupos():
    # un cuadro de train nunca está a menos de `margen` s de un cuadro de examen
    ex = [(100.0, 145.0)]
    for t in range(0, 400):
        if ev.tramo(t, ex, 10) == 'train':
            assert all(not (a - 10 <= t < b + 10) for a, b in ex)


def test_motivo_de_descarte_con_los_umbrales_calibrados():
    assert ev.motivo_descarte(5000, 150, 0.01) == ''
    assert ev.motivo_descarte(5000, 150, 0.10) == 'dedo en el lente'
    assert ev.motivo_descarte(300, 150, 0.01) == 'borroso'
    assert ev.motivo_descarte(5000, 10, 0.01) == 'oscuro'


def test_un_suelo_liso_sin_color_de_piel_no_es_un_dedo():
    import numpy as np
    gris = np.full((640, 360, 3), 140, np.uint8)
    assert ev.fraccion_dedo(gris) == 0.0
    piel = gris.copy()
    piel[470:, :, :] = (120, 150, 230)       # BGR de un tono piel liso en el 26 % inferior
    assert ev.fraccion_dedo(piel) > 0.06
