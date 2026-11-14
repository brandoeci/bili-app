import importlib.util
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location('candidatos_video', Path(__file__).parent.parent / 'scripts' / 'dataset' / 'candidatos_video.py')
cv = importlib.util.module_from_spec(spec)
sys.modules['candidatos_video'] = cv
spec.loader.exec_module(cv)

POSTE = [100, 50, 130, 450]


def test_se_respeta_el_umbral_de_cada_clase():
    m = [['curb', 0.16, 0, 500, 300, 560], ['curb', 0.10, 0, 600, 300, 660], ['pole', 0.25, *POSTE], ['pole', 0.31, 400, 50, 430, 450]]
    r = cv.unir_candidatos(m, [])
    assert [(c['clase'], c['conf']) for c in r] == [('pole', 0.31), ('curb', 0.16)]


def test_dos_cajas_casi_iguales_de_la_misma_clase_se_funden():
    m = [['pole', 0.6, *POSTE], ['pole', 0.4, 102, 52, 131, 449]]
    assert len(cv.unir_candidatos(m, [])) == 1


def test_clases_distintas_sobre_la_misma_zona_se_conservan_las_dos():
    r = cv.unir_candidatos([['pothole', 0.5, 0, 0, 100, 100], ['curb', 0.4, 0, 0, 100, 100]], [])
    assert {c['clase'] for c in r} == {'pothole', 'curb'}


def test_una_caja_de_dino_repetida_con_un_poste_del_modelo_no_se_agrega():
    r = cv.unir_candidatos([['pole', 0.6, *POSTE]], [[101, 52, 131, 449, 0.5]])
    assert len(r) == 1 and r[0]['fuente'] == 'modelo'


def test_dino_agrega_un_poste_nuevo_si_es_alargado_y_pasa_el_umbral():
    r = cv.unir_candidatos([], [[400, 50, 430, 450, 0.4], [10, 10, 200, 60, 0.9], [300, 50, 330, 450, 0.2]])
    assert len(r) == 1 and r[0]['fuente'] == 'dino' and r[0]['clase'] == 'pole'
