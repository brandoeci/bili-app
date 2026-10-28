# Dataset y modelo propio de peligros

COCO no tiene huecos, bordillos ni escaleras. Este flujo arma un dataset con las clases de Bili y afina un
detector aparte (`models/bili-hazards.pt`) que corre junto al de COCO.

Clases (`BILI_CLASSES` en `scripts/dataset/prepare_dataset.py`): `pothole`, `manhole`, `curb`,
`stairs_down`, `stairs_up`, `stairs`, `pole`, `obstacle`. `manhole` va aparte a propósito: una tapa de
alcantarilla se confunde con un hueco y conviene que el modelo aprenda la diferencia.

## 1. Descargar las fuentes (requiere cuenta gratuita de Roboflow)

Roboflow no permite la descarga anónima. En cada página: **Download Dataset → Format `YOLOv8` → download zip**
y descomprimir en `data/raw/<nombre>/`.

| Carpeta | Página | Licencia |
|---|---|---|
| `data/raw/sod` | https://universe.roboflow.com/lamao/sod-enect | CC BY 4.0 |
| `data/raw/pothole-stair` | https://universe.roboflow.com/devansh2205/pothole-stair_detectionv2 | CC BY 4.0 |
| `data/raw/pothole` | https://universe.roboflow.com/pothole-detector-dmdod/pothole-clzln | CC BY 4.0 |
| `data/raw/pothole-stair` | https://universe.roboflow.com/devansh2205/pothole-stair_detection | CC BY 4.0 |
| `data/raw/strairs`, `strairs2` | https://universe.roboflow.com/esera/strairs · `/strairs-2` | CC BY 4.0 |
| `data/raw/manhole` | https://universe.roboflow.com/ff-vt4js/manhole-cover-detection | dominio público |
| `data/raw/bogota` | fotos propias, etiquetadas en Roboflow y exportadas igual | propia |

Descartadas tras mirar las cajas: `Dataset UpStairs` (una caja por peldaño y primeros planos de los pies,
no se parece a lo que ve un celular a la altura del pecho) y `manholecover-detect` (clases en pinyin, sin
verificar). `Up Down` viene en formato "folder", no es de detección.

Dos fuentes tienen clases con nombres que las reglas no entienden y se fuerzan con `--map`:
`--map manhole:0=manhole --map strairs:-=stairs`.

Cada carpeta debe tener `data.yaml` y `train|valid|test/{images,labels}`.

## 2. Revisar el mapeo de clases ANTES de construir

```
python scripts/dataset/prepare_dataset.py --list data/raw/sod data/raw/pothole-stair
```

Muestra cada clase original y a cuál de las de Bili va. Lo que diga `(se descarta)` y sea un peligro real
(por ejemplo un nombre raro de escalera) se arregla añadiendo una regla en `RULES`. Las reglas se escribieron
sin ver los nombres reales de estos datasets, por eso este paso es obligatorio.

## 3. Construir

```
python scripts/dataset/prepare_dataset.py data/raw/sod data/raw/pothole data/raw/pothole-stair data/raw/strairs \
    data/raw/strairs2 data/raw/manhole --map manhole:0=manhole --map strairs:-=stairs --out data/bili-dataset
```

Imprime las instancias por clase y marca las que tienen menos de 300. Revisar el informe antes de entrenar:
una clase con pocos ejemplos saldrá con mAP bajo y no debe darse por detectada.

## 4. Entrenar (en GPU)

```
python scripts/dataset/train.py --device 0
```

En CPU tarda días. Colab o Kaggle sirven: subir `data/bili-dataset` y `scripts/dataset/train.py`,
instalar `ultralytics`, ejecutar y traer `best.pt` a `models/bili-hazards.pt`. El script imprime el mAP en
test por clase.

## Límites

- Estas fuentes son de otros países; sin fotos de Bogotá no se puede afirmar que el modelo funcione aquí.
- `stairs` (sin dirección) viene de datasets que no distinguen subida de bajada. Solo `stairs_down` y
  `stairs_up` sirven para avisar del peligro real; hay que etiquetar la dirección con fotos propias.
- Un buen mAP en test no es una prueba de seguridad. Falta medir falsos negativos con grabaciones reales.

## Resultados del modelo v2 (YOLO26s, 25 épocas, T4)

Dataset: 25.277 imágenes de train, 3.806 de val y 1.880 de test. Evaluado en test, en CPU:

| Clase | mAP50-95 v1 | mAP50-95 v2 |
|---|---|---|
| pothole | 0,455 | 0,514 |
| manhole | 0 | 0,654 |
| curb | 0,291 | 0,323 |
| stairs_down | 0 | 0,220 |
| stairs_up | 0 | 0,362 |
| stairs | 0,181 | 0,309 |
| pole | 0,197 | 0,185 |
| obstacle | 0,677 | 0,678 |
| **total** | **0,225** | **0,406** (mAP50 0,654, recall 0,644) |

El v1 no tenía datos de tapas ni de escaleras con dirección, por eso sale con 0 en ellas. La validación
en Colab dio 0,385 en total y 0,156 en `curb`; no se explica la diferencia con la medición local, así que las
cifras de `curb`, `pole` y escaleras son inciertas (pocas instancias en test).

Son métricas del test del dataset, no de la calle de Bogotá.
