# -*- coding: utf-8 -*-
"""
app.py — VisualShelf: servidor web del detector de huecos en góndolas.

Sirve la interfaz (carpeta static/) y una API mínima que usa motor.py (el mismo código del notebook V4.1b):
    GET  /api/config     -> parámetros del modelo, tiendas y límites
    POST /api/analizar   -> analiza UNA foto (JSON con la imagen en base64) y devuelve el resultado y la imagen anotada

Solo usa la biblioteca estándar de Python para el servidor: no hace falta instalar Flask, FastAPI ni Gradio.

Ejecutar:
    python app.py                                  # http://127.0.0.1:7860
    python app.py --modelo best.pt --parametros parametros_v4.json --puerto 7860
Variables de entorno equivalentes: MODELO, PARAMETROS, PORT, TIENDAS ("Walmart 2587;Walmart 1104").
"""
import argparse, base64, io, json, mimetypes, os, threading, time, traceback
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import numpy as np
import cv2
from PIL import Image, ImageOps

import motor

AQUI = Path(__file__).resolve().parent
ESTATICOS = AQUI / "static"
MAX_BYTES = 30 * 1024 * 1024      # tamaño máximo de una petición (una foto en base64)
LADO_MAX = 4000                   # fotos más grandes se reducen (el detector trabaja a 1024 px)
LADO_VISOR = 1600                 # tamaño de la imagen anotada que se envía al navegador
MAX_FOTOS = 30                    # por lote (lo controla la interfaz)

ESTADO = {"modelo_ok": False, "error": None, "parametros": {}, "tiendas": ["Walmart 2587"]}
CANDADO = threading.Lock()        # motor.py usa variables globales: se analiza una foto a la vez


# ----------------------------------------------------------------------------------------------------------------------
# Lógica
# ----------------------------------------------------------------------------------------------------------------------
def decodificar_imagen(dato):
    """Recibe un data URL o base64. Devuelve (imagen BGR, fecha de captura EXIF o None)."""
    if "," in dato[:100]:
        dato = dato.split(",", 1)[1]
    crudo = base64.b64decode(dato)
    with Image.open(io.BytesIO(crudo)) as im:
        fecha = None
        try:
            exif = im.getexif()
            valor = exif.get_ifd(0x8769).get(36867) or exif.get(306)          # DateTimeOriginal o DateTime
            if valor:
                fecha = datetime.strptime(str(valor).strip()[:19], "%Y:%m:%d %H:%M:%S").isoformat()
        except Exception:
            fecha = None
        im = ImageOps.exif_transpose(im).convert("RGB")                        # respeta la orientación del celular
        if max(im.size) > LADO_MAX:
            im.thumbnail((LADO_MAX, LADO_MAX))
        return cv2.cvtColor(np.asarray(im), cv2.COLOR_RGB2BGR), fecha


def a_data_url(img_rgb, lado=LADO_VISOR, calidad=85):
    if img_rgb is None:
        return None
    h, w = img_rgb.shape[:2]
    s = min(1.0, lado / max(h, w))
    if s < 1:
        img_rgb = cv2.resize(img_rgb, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, calidad])
    return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode() if ok else None


def analizar(payload):
    if not ESTADO["modelo_ok"]:
        raise RuntimeError(ESTADO["error"] or "El modelo no está cargado")
    nombre = str(payload.get("nombre") or "imagen")[:200]
    umbral = float(payload.get("umbral", 30)) / 100.0
    conf = float(payload.get("confianza", motor.CONF_DET))
    if not (0.0 < umbral < 1.0) or not (0.01 <= conf <= 0.99):
        raise ValueError("Umbral o confianza fuera de rango")
    t0 = time.time()
    try:
        im, fecha = decodificar_imagen(payload.get("imagen", ""))
    except Exception:
        im, fecha = None, None
    with CANDADO:
        motor.ajustar(umbral_stock=umbral, conf_det=conf)
        r = motor.analizar_imagen(im, nombre, ancho_dibujo=LADO_VISOR, banda=False)
    return {
        "nombre": nombre, "estado": r["estado"], "estado_texto": r["estado_texto"], "stock_pct": r["stock_pct"],
        "productos": r["productos"], "detecciones": r["detecciones"], "filas": r["filas"], "huecos": r["huecos"],
        "filas_bajas": r["filas_bajas"], "motivos": r["motivos"], "fecha_captura": fecha,
        "tiempo_s": round(time.time() - t0, 2), "umbral_pct": round(umbral * 100), "confianza": conf,
        "imagen_anotada": a_data_url(r["imagen"]),
    }


# ----------------------------------------------------------------------------------------------------------------------
# Servidor HTTP
# ----------------------------------------------------------------------------------------------------------------------
class Manejador(BaseHTTPRequestHandler):
    server_version = "VisualShelf/1.0"

    def log_message(self, fmt, *args):            # registro corto en consola
        print(f"[{datetime.now():%H:%M:%S}] {self.address_string()} {fmt % args}")

    def _json(self, codigo, obj):
        cuerpo = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(cuerpo)

    def do_GET(self):
        ruta = urlparse(self.path).path
        if ruta == "/api/config":
            p = ESTADO["parametros"]
            return self._json(200, {"modelo_ok": ESTADO["modelo_ok"], "error": ESTADO["error"], "tiendas": ESTADO["tiendas"],
                                    "umbral_pct": round(float(p.get("umbral_stock", 0.30)) * 100), "confianza": p.get("conf_det", 0.35),
                                    "modelo": p.get("modelo"), "bordes": p.get("bordes"), "zona": p.get("zona"), "max_fotos": MAX_FOTOS})
        if ruta in ("/", ""):
            ruta = "/index.html"
        archivo = (ESTATICOS / ruta.lstrip("/")).resolve()
        if ESTATICOS.resolve() not in archivo.parents or not archivo.is_file():        # evita salir de static/
            return self._json(404, {"error": "no encontrado"})
        datos = archivo.read_bytes()
        tipo = mimetypes.guess_type(archivo.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", tipo + ("; charset=utf-8" if tipo.startswith("text/") or tipo.endswith("javascript") else ""))
        self.send_header("Content-Length", str(len(datos)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(datos)

    def do_POST(self):
        if urlparse(self.path).path != "/api/analizar":
            return self._json(404, {"error": "no encontrado"})
        largo = int(self.headers.get("Content-Length") or 0)
        if largo <= 0 or largo > MAX_BYTES:
            return self._json(413, {"error": f"La foto es demasiado grande (máx. {MAX_BYTES // 1024 // 1024} MB)"})
        try:
            payload = json.loads(self.rfile.read(largo).decode("utf-8"))
            return self._json(200, analizar(payload))
        except (ValueError, KeyError) as e:
            return self._json(400, {"error": str(e)})
        except Exception as e:
            traceback.print_exc()
            return self._json(500, {"error": f"Error al analizar: {e}"})


def main():
    ap = argparse.ArgumentParser(description="VisualShelf — app web del detector de huecos en góndolas")
    ap.add_argument("--modelo", default=os.environ.get("MODELO", str(AQUI / "best.pt")))
    ap.add_argument("--parametros", default=os.environ.get("PARAMETROS", str(AQUI / "parametros_v4.json")))
    ap.add_argument("--puerto", type=int, default=int(os.environ.get("PORT", 7860)))
    ap.add_argument("--host", default=os.environ.get("HOST", "0.0.0.0"))
    ap.add_argument("--tiendas", default=os.environ.get("TIENDAS", "Walmart 2587"), help='lista separada por ";"')
    a = ap.parse_args()
    ESTADO["tiendas"] = [t.strip() for t in a.tiendas.split(";") if t.strip()] or ["Tienda"]
    try:
        params = a.parametros if Path(a.parametros).exists() else None
        ESTADO["parametros"] = motor.cargar(a.modelo, params)
        ESTADO["modelo_ok"] = True
        print("Modelo cargado:", ESTADO["parametros"])
        if params is None:
            print(f"Aviso: no se encontró {a.parametros}; se usan los parámetros por defecto.")
    except Exception as e:
        ESTADO["error"] = f"No se pudo cargar el modelo ({e}). Copia best.pt junto a app.py o indica --modelo."
        print(ESTADO["error"])
    srv = ThreadingHTTPServer((a.host, a.puerto), Manejador)
    print(f"VisualShelf listo en http://127.0.0.1:{a.puerto}  (Ctrl+C para detener)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
