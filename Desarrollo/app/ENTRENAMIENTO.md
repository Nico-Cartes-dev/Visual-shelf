# Entrenar con fotos de una carpeta

Ejecuta los comandos desde esta carpeta (`app`). Se ajusta el `best.pt`
existente; el original no se reemplaza. No es necesario subir las fotos a Roboflow.

## 1. Preparar fotos y etiquetas

Pon las fotos y sus etiquetas juntas, por ejemplo `C:\dataset\fotos\foto01.jpg`
y `C:\dataset\fotos\foto01.txt`. Tambien puedes separar los TXT con
`--etiquetas "C:\dataset\etiquetas"`, manteniendo los mismos nombres y subcarpetas.

Cada TXT contiene una linea por producto:

```text
0 0.50 0.50 0.20 0.30
```

Formato: `clase centro_x centro_y ancho alto`, con coordenadas normalizadas
entre 0 y 1. Usa las mismas clases y el mismo orden que el modelo original;
el script los obtiene de `best.pt` y los muestra antes de entrenar.
Un TXT vacio significa una foto sin objetos de las clases objetivo; usalo
solo cuando realmente no aparezcan. Anota todos los productos visibles.
Puedes etiquetar manualmente con herramientas como CVAT o Label Studio y
exportar en formato YOLO de deteccion. Las predicciones del modelo pueden
ayudar como borrador, pero deben corregirse antes de usarlas como etiquetas.

## 2. Instalar y entrenar

```powershell
python -m pip install -r requirements.txt
python entrenar.py --fotos "C:\dataset\fotos"
```

Opciones para GPU NVIDIA con PyTorch compatible con CUDA instalado:

```powershell
python entrenar.py --fotos "C:\dataset\fotos" --device 0 --epochs 100 --imgsz 640 --batch 2
```

Para CPU usa `--device cpu`; sera mas lento. Si falta memoria GPU, baja
`--batch` a 1. Puedes probar `--imgsz 1024` para productos pequenos si tu
hardware lo permite. La instalacion de requirements por si sola no garantiza CUDA.

El script copia las fotos y etiquetas a una carpeta nueva, separa 80 % para
entrenar y 20 % para validar, y genera `data.yaml`. No modifica los originales.
Necesita al menos dos fotos, pero ese minimo no basta para evaluar calidad.
Evita fotos casi identicas de una misma gondola: la division es aleatoria
por foto y no agrupa por tienda o sesion. Para una evaluacion fiable, reserva
ademas fotos independientes de otras sesiones que no entren en esta carpeta.
Conviene mezclar ejemplos anteriores con los nuevos para reducir el olvido.

## 3. Probar el resultado en la app

El nuevo modelo queda en `entrenamientos/ajuste_.../modelo/weights/best.pt`.
Ultralytics muestra tambien metricas y graficos dentro de `modelo`.

```powershell
python app.py --modelo "entrenamientos\ajuste_...\modelo\weights\best.pt"
```

Reemplaza `ajuste_...` por la carpeta real y compara con fotos independientes
antes de adoptar el modelo nuevo. Este ajuste inicia un entrenamiento nuevo
desde los pesos existentes; no reanuda el estado de una ejecucion interrumpida.
