"""Ajusta best.pt con fotos locales y etiquetas YOLO revisadas."""
import argparse
import json
import math
from pathlib import Path
import random
import shutil
import tempfile


BASE = Path(__file__).resolve().parent
EXTENSIONES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def preparar(fotos, etiquetas, destino, clases, fraccion=0.2, semilla=42):
    """Valida antes de copiar; conserva subcarpetas y no modifica originales."""
    imagenes = sorted(p for p in fotos.rglob("*") if p.is_file() and p.suffix.lower() in EXTENSIONES)
    if len(imagenes) < 2:
        raise ValueError("Se necesitan al menos 2 fotos para separar entrenamiento y validacion.")
    pares, vistos, objetos = [], set(), 0
    for foto in imagenes:
        relativo = foto.relative_to(fotos)
        clave = relativo.with_suffix("").as_posix().casefold()
        if clave in vistos:
            raise ValueError(f"Dos fotos comparten nombre de etiqueta: {relativo}")
        vistos.add(clave)
        etiqueta = etiquetas / relativo.with_suffix(".txt")
        if not etiqueta.is_file():
            raise ValueError(f"Falta etiqueta: {etiqueta}. Etiqueta la foto antes de entrenar.")
        for numero, linea in enumerate(etiqueta.read_text(encoding="utf-8-sig").splitlines(), 1):
            if not linea.strip():
                continue
            try:
                valores = [float(v) for v in linea.split()]
                if len(valores) != 5 or not all(math.isfinite(v) for v in valores):
                    raise ValueError()
                clase, x, y, ancho, alto = valores
                if not clase.is_integer() or not 0 <= clase < clases:
                    raise ValueError()
                if not (0 <= x <= 1 and 0 <= y <= 1 and 0 < ancho <= 1 and 0 < alto <= 1):
                    raise ValueError()
            except ValueError:
                raise ValueError(f"Etiqueta YOLO invalida: {etiqueta}, linea {numero}") from None
            objetos += 1
        pares.append((foto, etiqueta, relativo))
    if not objetos:
        raise ValueError("Todas las etiquetas estan vacias: no hay productos anotados.")
    random.Random(semilla).shuffle(pares)
    n_val = max(1, min(len(pares) - 1, round(len(pares) * fraccion)))
    for i, (foto, etiqueta, relativo) in enumerate(pares):
        grupo = "val" if i < n_val else "train"
        for origen, tipo, ruta in ((foto, "images", relativo),
                                   (etiqueta, "labels", relativo.with_suffix(".txt"))):
            salida = destino / tipo / grupo / ruta
            salida.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(origen, salida)
    return len(pares) - n_val, n_val


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fotos", type=Path, required=True, help="Carpeta de fotos (incluye subcarpetas)")
    parser.add_argument("--etiquetas", type=Path, help="Carpeta de TXT; por defecto, junto a las fotos")
    parser.add_argument("--modelo", type=Path, default=BASE / "best.pt")
    parser.add_argument("--salida", type=Path, default=BASE / "entrenamientos")
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batch", type=int, default=2)
    parser.add_argument("--device", default=None, help="0 para GPU NVIDIA, cpu para procesador")
    parser.add_argument("--val", type=float, default=0.2, help="Fraccion de validacion")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    if not 0 < args.val < 1:
        parser.error("--val debe estar entre 0 y 1")
    if min(args.epochs, args.imgsz, args.batch) < 1:
        parser.error("epochs, imgsz y batch deben ser positivos")
    fotos = args.fotos.resolve()
    etiquetas = (args.etiquetas or fotos).resolve()
    salida = args.salida.resolve()
    if not fotos.is_dir() or not etiquetas.is_dir() or not args.modelo.is_file():
        parser.error("Revisa las rutas de fotos, etiquetas y modelo.")
    if salida == fotos or fotos in salida.parents:
        parser.error("--salida debe estar fuera de la carpeta de fotos.")
    from ultralytics import YOLO
    modelo = YOLO(str(args.modelo.resolve()))
    if modelo.task != "detect":
        parser.error("Este script requiere un modelo de deteccion de cajas.")
    nombres = [modelo.names[i] for i in range(len(modelo.names))]
    salida.mkdir(parents=True, exist_ok=True)
    ejecucion = Path(tempfile.mkdtemp(prefix="ajuste_", dir=salida))
    dataset = ejecucion / "dataset"
    try:
        n_train, n_val = preparar(fotos, etiquetas, dataset, len(nombres), args.val, args.seed)
    except ValueError as error:
        parser.error(str(error))
    # JSON es tambien YAML valido y evita problemas con rutas de Windows.
    configuracion = dataset / "data.yaml"
    configuracion.write_text(json.dumps({"path": dataset.as_posix(), "train": "images/train",
                                         "val": "images/val", "names": nombres}, indent=2), encoding="utf-8")
    print(f"Fotos: {n_train} entrenamiento / {n_val} validacion. Clases: {nombres}")
    print(f"Resultados: {ejecucion}")
    opciones = dict(data=str(configuracion), epochs=args.epochs, imgsz=args.imgsz,
                    batch=args.batch, workers=0, seed=args.seed, patience=20,
                    project=str(ejecucion), name="modelo", exist_ok=False)
    if args.device is not None:
        opciones["device"] = args.device
    modelo.train(**opciones)
    print(f"Modelo nuevo: {modelo.trainer.best}")


if __name__ == "__main__":
    main()
