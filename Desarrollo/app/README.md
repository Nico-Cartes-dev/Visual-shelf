---
title: VisualShelf
emoji: 🛒
colorFrom: blue
colorTo: yellow
sdk: docker
app_port: 7860
pinned: false
---

# VisualShelf — análisis de góndolas

Interfaz web del detector de huecos en góndolas. Se suben fotos y, para cada una, se obtiene la **ocupación estimada**,
el estado (**Stock adecuado / Reabastecer / Revisión manual**) y la foto con las detecciones. Incluye historial, alertas,
resumen por tienda y descarga en CSV.

## Archivos

| Archivo | Qué es |
|---|---|
| `app.py` | Servidor web (solo biblioteca estándar de Python) y API: `GET /api/config`, `POST /api/analizar`. |
| `motor.py` | Detector y cálculo de stock, copiados tal cual del notebook V4.1b (mismos resultados). |
| `static/` | La interfaz: `index.html`, `styles.css`, `app.js`. |
| `best.pt` | Modelo entrenado (YOLOv8 + SKU-110K). |
| `parametros_v4.json` | Parámetros calibrados por el notebook (confianza 0.35, umbral 30 %, bordes desactivados). |
| `requirements.txt` | Librerías: ultralytics, opencv, scipy, numpy, pillow. |
| `lanzar_app_colab.ipynb` | Abre la app desde Google Colab con un enlace público. |
| `Dockerfile` | Para Hugging Face Spaces (SDK Docker) o cualquier servidor. |

## Opción 1 — En un computador

```bash
pip install -r requirements.txt
python app.py                  # abre http://127.0.0.1:7860
```
Opciones: `--puerto 8000`, `--modelo ruta/best.pt`, `--parametros ruta/parametros_v4.json`,
`--tiendas "Walmart 2587;Walmart 1104"`.

## Opción 2 — Google Colab (enlace público temporal, gratis)

1. Sube la carpeta `app` a tu Drive en `MyDrive/proyecto_gondolas/app/`.
2. Abre `lanzar_app_colab.ipynb` en Colab y ejecuta las celdas.
3. La última celda muestra un enlace `https://xxxx.trycloudflare.com` para compartir. Funciona mientras la sesión de Colab siga abierta.

## Opción 3 — Hugging Face Spaces (enlace permanente, gratis)

1. En huggingface.co → **New Space** → SDK **Docker** → plantilla **Blank** → hardware **CPU basic**.
2. En **Files → Add file → Upload files**, sube todo el contenido de esta carpeta (incluida `static/`).
3. El Space se construye solo (5–10 min la primera vez) y queda en `https://huggingface.co/spaces/<usuario>/<nombre>`.

## Notas

- El historial, las alertas y la configuración se guardan en el navegador de cada persona (no en el servidor).
- Si cambias la lógica en el notebook, vuelve a ejecutar su celda 6.9b para regenerar `parametros_v4.json`.
- Fotos recomendadas: frontales o con poco ángulo, 2–4 m de góndola, buena luz. Frutas y verduras a granel quedan fuera de alcance.
