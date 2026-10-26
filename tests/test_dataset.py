from __future__ import annotations

import importlib.util
from pathlib import Path

import cv2
import numpy as np
import yaml

_spec = importlib.util.spec_from_file_location(
    'prepare_dataset', Path(__file__).resolve().parent.parent / 'scripts' / 'dataset' / 'prepare_dataset.py')
prep = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(prep)


def _make_source(root: Path, names: list[str], samples: dict[str, list[str]]) -> Path:
    """samples: {stem: [líneas de etiqueta]} -> todas en train."""
    (root / 'train' / 'images').mkdir(parents=True)
    (root / 'train' / 'labels').mkdir(parents=True)
    (root / 'data.yaml').write_text(yaml.safe_dump({'names': names}))
    for stem, lines in samples.items():
        cv2.imwrite(str(root / 'train' / 'images' / f'{stem}.jpg'), np.zeros((32, 32, 3), np.uint8))
        (root / 'train' / 'labels' / f'{stem}.txt').write_text('\n'.join(lines))
    return root


def test_map_name_covers_common_roboflow_spellings():
    m = prep.map_name
    assert m('Pothole') == 'pothole' and m('potholes') == 'pothole'
    assert m('Manhole') == 'manhole' and m('sewer_cover') == 'manhole'
    assert m('downstairs') == 'stairs_down' and m('Stairs Down') == 'stairs_down'
    assert m('upstairs') == 'stairs_up'
    assert m('stairs') == 'stairs'          # sin dirección conocida
    assert m('Curb') == 'curb' and m('kerb') == 'curb'
    assert m('Electric Pole') == 'pole' and m('bollard') == 'pole'
    assert m('person') is None and m('car') is None   # los cubre el detector COCO
    # clases reales de SOD (sod-enect)
    assert m('spherical_roadblock') == 'obstacle' and m('warning_column') == 'obstacle'
    assert m('waste_container') == 'obstacle' and m('street_light') == 'pole'
    assert m('bus_stop') is None and m('cane') is None and m('tree') is None


def test_build_remaps_converts_polygons_and_reports(tmp_path, capsys):
    box = _make_source(tmp_path / 'sod', ['Curb', 'Stairs', 'Person'], {
        'a': ['0 0.5 0.5 0.2 0.2', '2 0.1 0.1 0.1 0.1'],      # curb + persona (se descarta la persona)
        'b': ['1 0.4 0.4 0.3 0.3'],                            # stairs
        'solo_persona': ['2 0.5 0.5 0.2 0.2'],                 # fondo sin clases útiles
    })
    seg = _make_source(tmp_path / 'ps', ['Pothole', 'Downstairs'], {
        'c': ['0 0.2 0.2 0.6 0.2 0.6 0.8 0.2 0.8'],            # polígono -> caja
        'd': ['1 0.5 0.5 0.1 0.1'],
    })
    out = tmp_path / 'out'
    prep.build([box, seg], out, neg_ratio=1.0, seed=0)

    cfg = yaml.safe_load((out / 'data.yaml').read_text())
    assert cfg['names'] == dict(enumerate(prep.BILI_CLASSES))
    labels = {p.name: p.read_text().split() for p in (out / 'labels' / 'train').glob('*.txt')}
    assert len(labels) == 5                                    # 4 con objetos + 1 fondo (neg_ratio=1)

    ids = {c: i for i, c in enumerate(prep.BILI_CLASSES)}
    a = labels['sod_train_a.txt']
    assert a[0] == str(ids['curb']) and len(a) == 5            # la persona desapareció
    poly = labels['ps_train_c.txt']
    assert poly[0] == str(ids['pothole'])
    cx, cy, w, h = map(float, poly[1:])
    assert (round(cx, 2), round(cy, 2), round(w, 2), round(h, 2)) == (0.4, 0.5, 0.4, 0.6)
    assert labels['ps_train_d.txt'][0] == str(ids['stairs_down'])
    assert labels['sod_train_solo_persona.txt'] == []          # fondo: imagen sin etiquetas

    report = capsys.readouterr().out
    assert 'POCAS' in report and 'Person' in report            # avisa de clases con pocos datos y de lo descartado


def test_background_fraction_is_respected(tmp_path):
    src = _make_source(tmp_path / 's', ['Curb', 'Person'], {
        'pos': ['0 0.5 0.5 0.2 0.2'], **{f'bg{i}': ['1 0.5 0.5 0.2 0.2'] for i in range(10)}})
    out = tmp_path / 'o'
    prep.build([src], out, neg_ratio=0.0, seed=0)
    assert len(list((out / 'labels' / 'train').glob('*.txt'))) == 1   # sin fondos
