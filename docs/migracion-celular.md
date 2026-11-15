# Migración: del servidor en el PC al celular

Rama `migracion-celular`. La versión que corre en el PC queda congelada en la rama `version-servidor-pc`.

## Por qué

El documento de arquitectura (entrega 2, `Bili-entrega2-final.tex`) fija una regla: *lo que afecta la seguridad corre en el
dispositivo; lo que aporta contexto, en la nube*. Hoy el celular manda cada cuadro por Wi-Fi al PC, que detecta, decide y devuelve
el texto del aviso. Eso incumple, por construcción, varios escenarios de calidad:

| Escenario | Qué exige | Hoy (servidor en el PC) |
|---|---|---|
| QA-1 Latencia | captura → inicio de la voz < 500 ms en el 95 % de los avisos, medido en el teléfono | sin medir; la red Wi-Fi está en el camino crítico |
| QA-2 Sin red | detección y aviso siguen sin conexión | sin el PC no hay aviso |
| QA-3 Abstención | confianza en banda intermedia → "deténgase", sin nombrar la clase, en el 100 % de los casos | **no existe** |
| QA-5 Privacidad | cero imágenes transmitidas | se transmiten todos los cuadros al PC |
| QA-7 Rendimiento sostenido | gama media; latencia del minuto 30 ≤ 1,2 × la del minuto 1; ≥ 1 h de batería | sin medir; solo hay un iPhone 14 Pro (gama alta) |
| QA-8 Observabilidad | cada aviso registrado con clase, confianza, conducta y latencia | no se registra la conducta ni la latencia de punta a punta |

## Decisiones tomadas

- **Prototipo en el navegador primero** (ONNX Runtime Web, WebGPU con WASM de respaldo). El paper prevé una app Android con
  TensorFlow Lite u ONNX Runtime; el navegador permite medir QA-1 y QA-7 sin construir la app. Límites conocidos en iOS: el bloqueo
  de pantalla en apps instaladas no funcionaba antes de iOS 18.4 y el audio en segundo plano no es fiable; la página debe quedar en
  primer plano con la pantalla encendida. Si eso no alcanza, la app nativa es el paso siguiente.
- **Entrada de 640 × 480 (vertical)**, la resolución de entrenamiento. Bajar a 416 queda solo como respaldo adaptativo en
  teléfonos lentos; su costo está medido (v6b: recall de poste 0,29 → 0,21, de bordillo 0,40 → 0,31 en la prueba general).
- **El modelo se elige con los exámenes**, no por versión.

## Motor de decisión y abstención (QA-3)

`app/core/decision.py` (y su copia `web/bili/decision.js`) convierte cada detección en una conducta. Primero la relevancia y después la
confianza: lo irrelevante (P3) se calla; por encima del umbral ALTO se avisa nombrando la clase; entre el BAJO y el ALTO, si está cerca o
en el camino (P0/P1), se dice "Deténgase: hay algo al frente y no estoy seguro de qué es" con prioridad máxima de voz; por debajo, silencio.
Si luego se confirma, se nombra.

Umbrales medidos con el v7a en el conjunto de prueba (`scripts/movil/umbrales_abstencion.py`): ALTO donde la franja acierta más de la mitad
de las veces, BAJO donde acierta 1 de cada 4 o menos. Fracción de objetos reales que reciben algún aviso: escaleras 0,47 -> 0,58, huecos
0,49 -> 0,62, bordillos 0,36 -> 0,46, postes 0,26 -> 0,36. Son del conjunto de prueba general, no de la vista del celular, y de un solo
modelo: se ajustan con `DECISION_UMBRALES` sin tocar código.

**Cuánto habla caminando** (`scripts/movil/avisos_por_minuto.py`, v7a, un cuadro por segundo, sin el detector de COCO; mide molestia,
no exactitud):

| Regla | Recorrido propio (11,8 min): "deténgase" / con clase | Video de Diego (14,8 min) |
|---|---|---|
| Sin abstención (como antes) | 0 / 5,5 por min | 0 / 3,7 por min |
| Con abstención, tal como está | **3,6** / 3,6 por min | 1,0 / 3,2 por min |
| A: "deténgase" solo si está en el camino | 1,4 / 3,8 | 0,5 / 3,1 |
| B: bordillo sin banda dudosa | 1,4 / 4,0 | 0,5 / 3,3 |
| A + B | 0,7 / 4,0 | 0,2 / 3,2 |

Tal como está pediría detenerse cada ~17 s en el recorrido propio; 28 de esos 43 "deténgase" son bordillos dudosos, casi siempre a un
lado. **Elegido: A + B** (15/11/2026), en `app/core/decision.py` y `web/bili/decision.js`. Costo aceptado: algo dudoso a un lado que se
cruce no pide detenerse hasta que esté al frente o se confirme; un bordillo con confianza menor a 0,50 no se menciona.
Medido a 8 cuadros/s con ByteTrack (mismas detecciones): recorrido propio de 7,7 con clase y 4,3 "deténgase" por minuto a 9,0 y 1,3;
video de Diego sin cambio (10,7 y 0,7).

**Corrección: a 8 cuadros/s habla más.** Con seguimiento y al ritmo de la app (`scripts/movil/seguimiento_videos.py`, 3 tramos de 60 s de
cada video, v7a, con abstención tal como está), el recorrido propio da 8,7 avisos con clase y 6,0 "deténgase" por minuto con BoT-SORT; el
de Diego, 11,7 y 0,3. La tabla de arriba (1 cuadro/s) subestima la carga; sirve para comparar variantes, no como cifra final.

## Seguimiento en el celular (fase 2b)

`web/bili/seguimiento.js` copia ByteTrack de Ultralytics paso a paso (filtro de Kalman, asociación en dos etapas, pistas sin confirmar,
olvido a los 30 cuadros y sus rarezas). Con las mismas detecciones da los mismos IDs, la misma caja entera y la misma confianza:
`scripts/movil/paridad_seguimiento.*`, 80 escenarios sintéticos (6 472 cuadros) y 6 tramos reales (2 880 cuadros), **0 diferencias**; la
prueba detecta cambiar el umbral de emparejamiento de 0,80 a 0,79 (289 cuadros distintos) y el olvido de 30 a 29 cuadros.

El servidor usa BoT-SORT, que además compensa el movimiento de la cámara con flujo óptico de OpenCV; eso no se copió. Lo que se pierde,
con las mismas detecciones (8 cuadros/s):

| | Recorrido propio | Video de Diego |
|---|---|---|
| Detecciones que llegan al motor, BoT-SORT | 70 % | 68 % |
| Ídem, ByteTrack (celular) | 52 % | 48 % |
| Ídem, BoT-SORT sin compensación | 52 % | 49 % |
| Avisos con clase / "deténgase" por min, BoT-SORT | 8,7 / 6,0 | 11,7 / 0,3 |
| Ídem, ByteTrack | 7,7 / 4,3 | 10,7 / 0,7 |

Toda la diferencia es la compensación de movimiento (sin ella BoT-SORT da lo mismo que ByteTrack). Lo que el seguidor esconde son sobre
todo parpadeos: dejarlos pasar sin ID sube los "deténgase" a 16,3 por minuto. Sin etiquetas no se sabe si los avisos que se pierden con
ByteTrack eran reales. El servidor sigue con BoT-SORT (`DETECTOR_TRACKER`, por defecto `botsort.yaml`). Opciones si hace falta la
compensación en el celular: OpenCV.js (~8 MB, costo por cuadro sin medir) o el giroscopio del teléfono (casi gratis, pero no se puede
comparar contra Python).

## Fases

| Fase | Qué | Cómo se sabe que sirvió | Estado |
|---|---|---|---|
| 1 | Detector en el celular: letterbox, decodificación y NMS en JS (`web/bili/deteccion.js`) | mismas detecciones que Python con el mismo ONNX; mismas métricas con el relleno del celular | **hecho en el PC**: 46 de 46 detecciones idénticas en 60 cuadros reales; examen de bordillos igual con el ONNX (v7a recall 0,26) |
| 1b | Medirlo en teléfonos: el iPhone 14 propio y el Android de Diego | ms por cuadro (mediana y p95) con el modelo elegido | **hecho** (abajo): el iPhone cumple; el Samsung A32 no |
| 2 | Motor de decisión en JS: distancia, zonas de cercanía, prioridades, **abstención (QA-3)** y alertas (`web/bili/{fusion,decision,alertas,cercania,etiquetas}.js`) | los mismos casos dan lo mismo en Python y en JS | **hecho**: 200 escenarios, 9 025 cuadros, 776 alertas (77 de "deténgase"), 0 diferencias; la prueba corre en `pytest` |
| 2b | Seguimiento (IDs entre cuadros) en JS: en el servidor lo da Ultralytics (`model.track`); en el celular no existe | IDs estables en los videos, comparados con Python | **hecho** con ByteTrack: 0 diferencias en 9 352 cuadros; sin compensación de movimiento llega el 52 % de las detecciones en vez del 70 % |
| 3 | App: cámara, voz, pantalla encendida, modelo en caché para uso sin red (QA-2, QA-5) | funciona en modo avión; ningún cuadro sale del teléfono | **construida** (`/local`, `web/local.html` y `web/sw.js`); probada en el iPhone el 15/11 (QA-8 30 de 30 avisos completos; captura → voz 231–250 ms con la voz libre, p95 3,8 s por la cola: arreglada con el carril `deteccion` de `voz.js`). Incluye la navegación de la versión con servidor (pregunta el destino, ruta de Google a pie, giros y cruces): la ruta se pide al servidor solo con coordenadas y después corre en el teléfono; sin red avisa que no puede buscar rutas. Sin descripción con Gemini (mandaría una imagen). Falta modo avión. Sin Worker: con WebGPU el modelo no bloquea la pantalla |
| 4 | Instrumentación: latencia captura → `onstart` de la voz (QA-1) y registro local de cada aviso (QA-8) | p95 < 500 ms; 100 % de avisos con los cuatro campos | **construida** dentro de `/local` (cifras en pantalla y registro descargable en JSON); falta medir caminando |
| 5 | Sostenido (QA-7): 30 min caminando, latencia y batería, en gama media | minuto 30 ≤ 1,2 × minuto 1; ≥ 1 h | pendiente |
| 6 | Validación (E4): exámenes, video de otra persona, prueba en campo acompañada | regla de decisión del paper | pendiente |

## Sin el PC: Bili en Google Cloud Run

El teléfono hace todo lo de la cámara; le faltaba de dónde bajar la página y los modelos la primera vez, y quién guarde la clave de
Google para las rutas. Eso es `app/nube.py` (sin PyTorch ni WebSocket, todo detrás de la clave), desplegado el 15/11/2026 en
Cloud Run (`us-east1`, máximo 1 instancia, 512 MB). Imagen privada en Artifact Registry; la clave de Maps y la de acceso son
secretos de Secret Manager (`bili-maps-key`, `bili-clave`).

```
gcloud builds submit --config cloudbuild.nube.yaml --substitutions=_IMAGEN=us-east1-docker.pkg.dev/PROYECTO/bili/nube --region us-east1 .
gcloud run deploy bili --image us-east1-docker.pkg.dev/PROYECTO/bili/nube --region us-east1 --allow-unauthenticated \
  --max-instances 1 --memory 512Mi --set-secrets GOOGLE_MAPS_API_KEY=bili-maps-key:latest,ONNX_SPIKE_CLAVE=bili-clave:latest
gcloud secrets versions access latest --secret bili-clave     # la clave del enlace /local?clave=...
```

El tope de 300 rutas al día vive en memoria: si la instancia se reinicia, se reinicia la cuenta.

## Velocidad medida en el teléfono (fase 1b)

`/onnx-spike` (ONNX_SPIKE=1) corre en el teléfono lo mismo que correrá la app: cámara, letterbox, modelos, decodificación, seguimiento,
fusión, decisión y alertas (los módulos de `web/bili/`). Mide de la captura a la alerta decidida, sin la voz. 100 cuadros por ronda.

iPhone 14, iOS 18.7, Safari, 15/11/2026 (tres corridas; los tiempos se repiten a ±3 ms):

| Configuración | Mediana | p95 | Cuadros/s |
|---|---|---|---|
| v7a solo, WebGPU | 152 ms | 162 ms | 6,6 |
| v7a + yolo26n (personas y vehículos), WebGPU | 222 ms | 230 ms | 4,5 |
| v7a solo, WebAssembly (respaldo) | 367 ms | 590 ms | 2,7 |

Android de Diego (Samsung Galaxy A32 4G, Helio G80, Chrome 157, 8 núcleos), 15/11/2026, por el túnel:

| Configuración | Mediana | p95 |
|---|---|---|
| v7a solo, WebGPU | 3 676 ms | 4 274 ms |
| v7a + yolo26n, WebGPU | 4 798 ms | 5 110 ms |
| v7a solo, WebAssembly | 16 144 ms | (2 cuadros) |

Unas 20 veces más lento que el iPhone y 7 veces por encima de QA-1; hasta preparar la imagen tarda 154 ms (iPhone: 6).

Segunda corrida, sin ahorro de batería: GPU **ARM Mali (arquitectura Bifrost), real, no por software**; descarga de 38 MB en 4 s (la red no
era el problema). **Piso** (yolo26n a 416 × 320, solo el modelo): WebGPU 654 ms de mediana y 2 672 ms de p95; WebAssembly 2 399 ms.
v7a solo con WebGPU 4 255 ms; con yolo26n 6 256 ms.

**Conclusión:** en esta clase de teléfono el navegador no cumple QA-1 ni con el modelo más chico. Como prevé el paper, el camino es una app
nativa de Android (TensorFlow Lite u ONNX Runtime con la GPU o el acelerador del teléfono) y, probablemente, un modelo de peligros tipo
"n" con entrada más chica. Es una gama media-baja de 2021: QA-7 queda sin cumplir en esa clase de teléfono y la app nativa
queda como trabajo futuro.

- Los dos modelos caben en QA-1 en el iPhone, con ~270 ms para que empiece la voz (falta medirla: fase 4).
- Sin WebGPU no se cumple: el p95 con WebAssembly pasa de 500 ms con un solo modelo.
- Seguimiento, fusión, decisión y alertas en JS: 0 ms.
- Cámara: en iOS hay que pedir `width: 640, height: 480`; con el teléfono vertical llega 480 × 640. Pedir 480 × 640 da una imagen
  horizontal que entra achicada y con bandas.

## Riesgos abiertos

- **Dos modelos.** El de peligros no tiene personas ni vehículos ("vehículo entrando al cruce" es una clase del paper). Con dos
  modelos tipo "s" el iPhone 14 Pro tardó 305 ms por cuadro solo en inferencia; en gama media no cabría en 500 ms. Opciones: un
  solo modelo que incluya persona y vehículos (hay que reentrenar) o un modelo COCO tipo "n" (140 ms los dos en el iPhone).
- **Regla de decisión del paper:** exige exhaustividad ≥ 0,80 en obstáculos críticos. Hoy ningún modelo la cumple en la vista del
  celular (bordillo 0,26 en el examen propio; escaleras alrededor de 0,6). Eso no lo resuelve la migración: es trabajo de datos.
- **Voz sin red:** en Android las voces de `speechSynthesis` dependen del motor del sistema; hay que comprobar que la voz en español
  esté descargada para uso sin conexión.
- **Licencia AGPL-3.0** de los pesos derivados de Ultralytics: los pesos quedan en el teléfono de quien use la app.

## Cómo probar lo hecho

```
node --test tests/js/deteccion.test.mjs
python -I scripts/movil/paridad_deteccion.py --modelo models/onnx/bili-hazards-v6b_640x480.onnx --salida CARPETA --cuadros a.jpg b.jpg ...
node scripts/movil/paridad_deteccion.mjs CARPETA      # sale con código 0 solo si todo coincide
python -I scripts/movil/paridad_seguimiento.py --salida seg.json [--detecciones dets.json]
node scripts/movil/paridad_seguimiento.mjs seg.json
```
