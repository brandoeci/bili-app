# Guía para tomar y etiquetar fotos de Bogotá

Los datos con los que se entrenó el detector de peligros son de otros países. Las fotos de Bogotá son lo que
más puede mejorar el modelo, sobre todo en **bordillos, escaleras (subida y bajada) y postes**, que son las
clases que hoy fallan más (mAP50-95 entre 0,19 y 0,36 en test; ver [dataset.md](dataset.md)).

## Seguridad antes de salir

- Grabe siempre **acompañado**. Una persona mira el camino; quien lleva el celular no debe caminar mirando la pantalla.
- Quédese en la acera. No se pare en la calzada para tomar un hueco ni una tapa.
- No se acerque a escaleras ni a bordes con el celular estirado en la mano; use el soporte o el bolsillo de camisa.
- Evite rostros y placas: si salen de frente y cerca, no use ese fotograma.
- Las fotos van a un proyecto **privado** de Roboflow. No las suba a redes ni al repositorio (`data/` está en `.gitignore`).

## Cómo sostener el celular

Hay que grabar **como se va a usar Bili**, porque el cálculo de distancia a huecos y bordillos supone la cámara
a la altura del pecho (~1,3 m) y horizontal.

- Celular **en vertical**, cámara trasera hacia adelante, a la **altura del pecho**, apuntando al frente
  (no hacia el suelo). Un soporte de pecho o el bolsillo de una camisa funcionan.
- Camine a paso normal. Si hay mucho movimiento, los fotogramas salen borrosos y el script los descarta.
- Una **variante extra** vale la pena: unas rutas con el celular inclinado ~20° hacia abajo, que es como mucha
  gente termina llevándolo.
- Grabe **video** (1080p, 30 fps). Es más rápido que tomar fotos sueltas: después se extraen los fotogramas.

## Qué grabar

Meta inicial por clase (fotogramas **etiquetados**, no videos). Son cifras de partida mías, no un mínimo probado:

| Clase | Meta | Qué buscar |
|---|---|---|
| `curb` bordillo | 300 | Bordes de acera, rampas, bordillos altos y bajos, rotos, de frente y en diagonal |
| `stairs_down` bajada | 250 | Escaleras que **descienden** hacia adelante: puentes, estaciones, accesos |
| `stairs_up` subida | 250 | Escaleras que **suben** hacia adelante |
| `pole` poste | 200 | Postes de luz, bolardos, señales, postes de semáforo |
| `pothole` hueco | 200 | Huecos en calzada y en acera, secos y con agua |
| `manhole` tapa | 150 | Tapas de alcantarilla, sumideros, rejillas |
| `obstacle` obstáculo | 150 | Conos, canecas, bicicletas y motos estacionadas, vendedores, materiales de obra |
| **sin peligros** | 10 % del total | Tramos de calle normales, sin ningún peligro. Evitan falsas alarmas |

Variedad, que pesa más que la cantidad:

- Distintos **barrios** y tipos de vía (centro, andenes angostos, ciclorruta, alrededor de TransMilenio).
- **Luz**: sol fuerte, nublado, sombra de árboles, al atardecer. Si es seguro y con compañía, algo de noche.
- **Distancia**: el peligro a 2, 4, 6 y 8 m, no solo pegado.
- **Mojado**: charcos, andén húmedo, reflejos.
- Cada escalera, desde **ambos lados** (subiendo y bajando). Así se separan las dos clases.

## Flujo de trabajo

1. Grabe y copie los videos a `data/bogota/videos/` (nombre sugerido: `YYYYMMDD_barrio_n.mp4`).
2. Saque los fotogramas, uno por segundo, descartando borrosos y repetidos:

   ```bash
   python scripts/dataset/extract_frames.py data/bogota/videos --out data/bogota/frames --every 1.0
   ```

3. Revise la carpeta de fotogramas y borre los que no sirvan (rostros, placas, nada útil).
4. Cree en Roboflow un proyecto **privado** de *Object Detection* y suba los fotogramas.
5. Cree **exactamente estas 8 clases**, con estos nombres:
   `pothole, manhole, curb, stairs_down, stairs_up, stairs, pole, obstacle`.
6. Etiquete (ver reglas abajo). Roboflow ofrece etiquetado asistido; revise cada caja, no la acepte sin mirar.
7. Genere una versión y expórtela como **YOLOv8** (zip). Descomprímala en `data/raw/bogota/`.
8. Avise a quien entrena: se suma con `prepare_dataset.py` (ver [dataset.md](dataset.md)).

## Reglas de etiquetado

- Caja **ajustada** al objeto completo, sin dejar mucho aire alrededor.
- **Escaleras**: una sola caja para todo el tramo, no una por peldaño. Si baja hacia adelante es `stairs_down`;
  si sube, `stairs_up`. Use `stairs` solo si de verdad no se puede saber.
- **Bordillo**: la caja cubre el borde visible de la acera, de extremo a extremo del tramo que se ve.
- **Hueco**: la caja cubre todo el hueco, incluido el borde roto. Los parches de asfalto y las grietas finas no cuentan.
- **Poste**: solo postes y bolardos; no etiquete árboles ni personas.
- Etiquete **todo** lo visible de las 8 clases en cada imagen. Un hueco sin etiquetar enseña al modelo a ignorarlo.
- Si no está seguro de qué es, o está a más de ~15 m y se ve diminuto, déjelo sin etiquetar y descarte la imagen
  si es dudosa.
- No etiquete personas ni vehículos: los cubre el detector COCO.

## Qué enviar al terminar una tanda

Una nota corta con: número de videos, fotogramas extraídos, fotogramas etiquetados por clase, barrios y qué
salió raro (clases que se confunden, escaleras sin dirección clara). Con eso se decide si falta algo antes de
reentrenar. Reentrenar cuesta unas 3 h de GPU, así que se junta todo en una sola tanda.
