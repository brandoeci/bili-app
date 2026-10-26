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
| `data/raw/bogota` | fotos propias, etiquetadas en Roboflow y exportadas igual | propia |

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
python scripts/dataset/prepare_dataset.py data/raw/sod data/raw/pothole-stair data/raw/bogota --out data/bili-dataset
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
- Falta enchufar `bili-hazards.pt` al pipeline como segundo detector (hoy `app/core/detector.py` carga uno solo).
