# Walmart Computer Vision - Proyecto Capstone

## Descripcion del Proyecto

### Problematica Abordada

En el entorno del retail y supermercados Walmart, la gestion manual de gondolas y la deteccion tardia de quiebres de stock representan perdidas de ventas y una deficiente experiencia de cliente. La deteccion manual de espacios vacios resulta lenta, costosa y dificil de escalar entre multiples salas y locales.

### Objetivos

* Objetivo General: Disenar e implementar una solucion automatizada basada en Inteligencia Artificial y Vision por Computador que analice imagenes de gondolas, determine la disponibilidad visual de productos y emita alertas cuando la disponibilidad sea inferior a un umbral critico (por ejemplo, menor al $30\%$).
* Objetivos Especificos:
  1. Detectar y segmentar repisas y productos en gondolas de exhibicion utilizando YOLOv8.
  2. Determinar espacios libres entre productos aplicando filtros de separacion natural para identificar huecos y calcular el porcentaje de stock disponible.
  3. Aplicar reglas tecnicas para enmascarar e ignorar zonas obstruidas u ofuscadas (personas, carros de compra, pilares o reflejos).
  4. Evaluar el desempeno del sistema con metricas cuantitativas (IoU, mAP, precision, recall y tiempos de procesamiento).
  5. Garantizar la reproducibilidad total del proyecto mediante una estructura de repositorio estandarizada y documentacion de ejecucion.

### Funcionalidades Principales

* Pipeline de Inferencia: Repisas (segmentacion) -> Productos (YOLOv8) -> Espacios libres entre productos -> Filtro de separacion natural -> Huecos -> Porcentaje de stock y alerta de reabastecimiento.
* Preprocesamiento e Ingesta de Datos: Conversion automatica de formatos (COCO/VOC) a YOLO, descartando clases no relevantes como etiquetas de precio.
* Integracion con Datasets Publicos y Propios: Procesamiento de datasets de Kaggle (Supermarket Shelves, Grocery Shelves) y fotos propias desde Roboflow (Proyecto Selfshelf).
* API REST basada en FastAPI para la ejecucion de inferencias y entrega de resultados estructurados en formato JSON.

---

## Estrategia y Justificacion Tecnica

### Tecnologias Utilizadas (Librerias Open Source)

* Lenguaje de Programacion: Python 3.10+
* Procesamiento de Vision por Computador: OpenCV, Pillow, NumPy, Albumentations
* Framework de Deep Learning: PyTorch, Ultralytics YOLOv8
* Datasets y Preprocesamiento: Roboflow API, KaggleHub
* Servicio de Inferencia / API: FastAPI, Uvicorn
* Entorno de Desarrollo y Persistencia: Google Colab con persistencia en Google Drive

### Justificacion Tecnica

* YOLOv8 y PyTorch: Seleccionados por su condicion Open Source, alto rendimiento en deteccion de objetos en tiempo real y solidez matematica para manejar variaciones de perspectiva, sombra e iluminacion en las tiendas.
* Pipeline en Dos Etapas (Productos + Espacios Libres): La combinacion de deteccion de productos con un filtro de separacion natural permite calcular con alta precision los huecos reales en la gondola sin confundir separaciones estructurales.
* FastAPI: Permite construir una interfaz asincrona de alta velocidad con validacion de datos automatica y documentacion OpenAPI estandar.

---

## Arquitectura de la Solucion

```text
[ Captura de Imagen / Stream ]
             │
             ▼
[ Preprocesamiento (OpenCV / Albumentations) ] ---> (Normalizacion, reduccion a 1280px y filtro de luz)
             │
             ▼
[ Inferencia IA (YOLOv8) ]                   ---> (Deteccion y bounding boxes de productos)
             │
             ▼
[ Analisis de Espacios Libres y Huecos ]     ---> (Filtro de separacion natural entre productos)
             │
             ▼
[ Calculo de Disponibilidad y Alerta ]       ---> (Estimacion % de stock; alerta si es < 30%)
             │
             ▼
[ API REST (FastAPI) ]                       ---> (Punto de contacto para integracion y reportes)
```

---

## Datasets Utilizados

* Datasets Publicos de Kaggle:
  - Supermarket Shelves Dataset (`humansintheloop/supermarket-shelves-dataset`)
  - Grocery Shelves (`unidpro/grocery-shelves`)
* Dataset Propio de Roboflow:
  - Workspace: `luis-valenzuela-s-workspace`
  - Proyecto: `selfshelf`
* Preparacion de Datos:
  1. Limpieza y Filtrado: Conversion de anotaciones a formato YOLO de una sola clase (`producto`), descartando etiquetas de precio (`price`, `price_tag`, `label`).
  2. Aumentacion de Datos: Aplicada en el conjunto de entrenamiento para mejorar la robustez frente a reflejos y oclusiones.
  3. Division del Dataset: $85\%$ Entrenamiento (`train`), $15\%$ Validacion (`val`).

---

## Estado Actual de la Implementacion

| Modulo / Componente              |    Estado    | % Avance | Observaciones y Evidencias                                                                   |
| :------------------------------- | :-----------: | :------: | :------------------------------------------------------------------------------------------- |
| Ingesta y Conversion de Datos    |   Terminado   |   100%   | Conversion COCO/VOC a YOLO y descarte de clases de precio completado.                        |
| Notebook de Entrenamiento (V3.1) |   Terminado   |   100%   | Pipeline completo implementado en`deteccion_huecos_gondolas_V3.1.ipynb`.                   |
| Detector de Productos (YOLOv8)   | En Desarrollo |   85%   | Modelo entrenado sobre datasets combinados; validacion sobre fotos propias.                  |
| Calculo de Huecos y % Stock      |   Terminado   |   90%   | Algoritmo de separacion natural y calculo de disponibilidad funcional.                       |
| Documentacion y Fase 1 / Fase 2  |   Terminado   |   100%   | Requerimientos, diagramas UML, historias de usuario, informes y diarioreflexion organizados. |

---

### Estructura de Carpetas y Organizacion del Codigo Fuente

Esta estructura corresponde exactamente a la organizacion del proyecto en el repositorio GitHub (`Visual-shelf`) y en las carpetas de Google Drive (`Fase 1` y `Fase 2`):

```text
Visual-shelf/
├── README.md                             
├── Fase 1/                               
│   ├── Anexos/
│   │   ├── Diseño/
│   │   │   ├── Diagrama de arquitectura/
│   │   │   │    ├── Arquitectura con colab.png
│   │   │   │    └── Arquitectura con local.png     
│   │   │   ├── Diagramas particulares por cada C.U_/
│   │   │   │    └── (cada caso de uso esta dentro)casos_de_uso_walmart_capstone.drawio
│   │   │   ├── Mockups/
│   │   │   │    ├── Mockup-01.jpg
│   │   │   │    ├── Mockup-02.jpg
│   │   │   │    ├── Mockup-03.jpg
│   │   │   │    └── Mockup-04.jpg
│   │   │   ├── Diagrama general de Caso de Uso.xml
│   │   │   ├── Lista de C.U. _ Historias de Usuario, Epicas, Sprint, etc.xlsx
│   │   │   ├── Lista de requerimientos funcionales y no funcionales.xlsx
│   │   │   └── Plantillas de C.U. por cada C.U_
│   │   ├── Gestion/
│   │   │   └── Actas de reunion/
│   │   │   │    └── Acta_Reunion_1_Walmart_Chile.docx
│   │   │   ├── Archivo README.docx
│   │   │   ├── Carta Gantt.xlsx
│   │   │   ├── Matriz RACI.xlsx
│   │   │   └── Plan de riesgo.xlsx
│   │   ├── Archivo README.docx
│   │   ├── Carta Gantt.xlsx
│   │   ├── Matriz RACI.xlsx
│   │   └── Plan de riesgo.xlsx
│   └── Documentos Administrativos/
│        └── Fase 1/
│            ├── Evidencias Grupales/
│            │    ├── 1.4_APT122_FormativaFase1.docx
│            │    ├── 1.5_GuiaEstudiante_Fase 1_Definicion Proyecto APT.docx
│            │    ├── PLANILLA DE EVALUACIÓN FASE 1.xlsx
│            │    └── Presentacion idea de proyecto.docx
│            └── Evidencias Individuales/
│                  ├── Cartes_nicolas_1.2_APT122_DiarioReflexionFase1.pdf
│                  ├── Cartes_nicolas_1.3_APT122_AutoevaluacionFase1.docx
│                  ├── Luengo_david_1.1_APT122_AutoevaluacionCompetenciasFase1.pdf
│                  ├── Luengo_david_1.2_APT122_DiarioReflexionFase1.pdf
│                  ├── Luengo_david_1.3_APT122_AutoevaluacionFase1.docx
│                  ├── Saldias_Luis_1.1_APT122_AutoevaluacionCompetenciasFase1.pdf
│                  ├── Saldias_Luis_1.2_APT122_DiarioReflexionFase1.pdf
│                  ├── Saldias_Luis_1.3_APT122_AutoevaluacionFase1.docx
│                  ├── cartes_nicolas_1.1_APT122_AutoevaluacionCompetenciasFase1.pdf
│                  ├── flores_eric_1.1_APT122_AutoevaluacionCompetenciasFase1.pdf
│                  ├── flores_eric_1.2_APT122_DiarioReflexionFase1.docx
│                  └── flores_eric_1.3_APT122_AutoevaluacionFase1.docx         
└── Fase 2/                               
    ├── 2.4_GuiaEstudiante_Fase 2_DesarrolloProyecto APT.docx
    ├── 2.4_GuiaEstudiante_Fase2_DesarrolloProyectoAPT(español).docx
    ├── Cartes_Nicolas_2.1_APT122_DiarioReflexionFase2.docx
    ├── Flores_Eric_2.1_APT122_DiarioReflexionFase2.docx
    ├── Luengo_David_2.1_APT122_DiarioReflexionFase2.docx
    ├── Saldias_Luis_2.1_APT122_DiarioReflexionFase2.docx
    ├── Informe_APT_Fase2_tres_secciones_modificado.docx
    └── modelos/
        └── deteccion_huecos_gondolas_V3.1.ipynb
```

### Instrucciones para Instalar Dependencias, Configurar y Ejecutar la Aplicacion

1. Clonar el repositorio desde GitHub:

```bash
git clone https://github.com/Nico-Cartes-dev/Visual-shelf.git
cd Visual-shelf
```

2. Crear y activar el entorno virtual de Python:

```bash
python -m venv venv

# En Linux o macOS:
source venv/bin/activate

# En Windows:
.\venv\Scripts\activate
```

3. Instalar las dependencias Open Source requeridas:

```bash
pip install ultralytics roboflow albumentations kagglehub opencv-python torch pillow matplotlib
```

4. Ejecucion del Notebook de Entrenamiento e Inferencia:
   Abrir y ejecutar el notebook `Fase 2/modelos/deteccion_huecos_gondolas_V3.1.ipynb` en Google Colab o Jupyter Lab.

* Configurar la clave API de Roboflow en las variables de entorno o Secrets de Colab (`ROBOFLOW_API_KEY`).
* El notebook realiza automaticamente la descarga de datasets desde Kaggle, la restauracion de cache en Google Drive, la conversion a formato YOLO y la ejecucion del pipeline de deteccion.

5. Semilla de Reproducibilidad:
   El codigo fija explicitamente las semillas de aleatoriedad al inicio del pipeline:

```python
SEED = 42
random.seed(SEED)
np.random.seed(SEED)
torch.manual_seed(SEED)
```

---

## Analisis de Resultados Preliminares (20 Casos)

* Evaluacion sobre Fotos Propias (Roboflow `selfshelf`): Evaluacion del modelo sobre 44 fotografias propias capturadas en gondolas reales.
* Mejores Casos: Deteccion precisa de productos individuales y calculo exacto del porcentaje de disponibilidad en gondolas bien iluminadas.
* Peores Casos / Desafios: Dificultades observadas en productos con reflejos intensos o zonas de sombras profundas. Se aplican filtros de separacion natural y aumentacion de datos para mitigar estos errores.

---

## Equipo y Supervision

* Integrantes del Equipo:
  - Nicolas Cartes (`ni.cartesg@duocuc.cl`)
  - Eric Flores (`eri.flores@duocuc.cl`)
  - David Luengo (`da.luengo@duocuc.cl`)
  - Luis Saldias (`lu.saldiasv@duocuc.cl`)
* Repositorio GitHub: https://github.com/Nico-Cartes-dev/Visual-shelf
* Proyecto: Walmart Computer Vision - Capstone (APT122)
* Supervisores: Arturo Vargas (`arvargas@profesor.duoc.cl`) / Jose Larrain
