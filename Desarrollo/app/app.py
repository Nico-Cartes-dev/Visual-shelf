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
Variables de entorno: MODELO, PARAMETROS, PORT, SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY.
"""
import argparse, base64, io, json, mimetypes, os, threading, time, traceback
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs
import hashlib
from central import Central, ErrorAPI, uuid

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

ESTADO = {"modelo_ok": False, "error": None, "parametros": {}}
CANDADO = threading.Lock()        # motor.py usa variables globales: se analiza una foto a la vez
CENTRAL = Central()


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
    if im is None:
        raise ValueError("La imagen no es valida")
    if not CANDADO.acquire(blocking=False):
        raise ErrorAPI(429, "El detector esta ocupado. Reintenta esta foto en unos segundos.")
    try:
        motor.ajustar(umbral_stock=umbral, conf_det=conf)
        r = motor.analizar_imagen(im, nombre, ancho_dibujo=LADO_VISOR, banda=False)
    finally:
        CANDADO.release()
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

    def token(self):
        cabecera = self.headers.get("Authorization", "")
        if not cabecera.startswith("Bearer ") or len(cabecera) > 16000:
            raise ErrorAPI(401, "Inicia sesion para continuar.")
        return cabecera[7:]

    def cuerpo(self):
        try:
            largo = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise ErrorAPI(400, "Longitud invalida") from None
        if not 0 < largo <= MAX_BYTES:
            raise ErrorAPI(413, "Peticion vacia o demasiado grande (maximo 30 MB).")
        dato = json.loads(self.rfile.read(largo))
        if not isinstance(dato, dict):
            raise ErrorAPI(400, "Se esperaba un objeto JSON.")
        return dato

    def api(self, metodo):
        ruta = urlparse(self.path).path
        try:
            if ruta == "/api/auth-config" and metodo == "GET":
                return self._json(200, CENTRAL.config())
            token = self.token()
            usuario = CENTRAL.usuario(token)
            if ruta == "/api/config" and metodo == "GET":
                p = ESTADO["parametros"]
                return self._json(200, {**p, "modelo_ok": ESTADO["modelo_ok"], "error": ESTADO["error"],
                    "tiendas": CENTRAL.tiendas(token), "usuario": {"id": usuario["id"], "email": usuario.get("email", "")},
                    "umbral_pct": round(float(p.get("umbral_stock", .3))*100), "confianza": p.get("conf_det", .35), "max_fotos": MAX_FOTOS})
            if ruta == "/api/resumen" and metodo == "GET":
                return self._json(200, CENTRAL.pedir("/rest/v1/rpc/resumen_visualshelf", token, "POST", {}))
            if ruta == "/api/analisis" and metodo == "GET":
                q = parse_qs(urlparse(self.path).query)
                pagina = max(0, int(q.get("pagina", [0])[0]))
                filtros = {"select": "*,tiendas(nombre)", "estado_proceso": "eq.completo", "order": "created_at.desc,id.desc",
                           "limit": "50", "offset": str(pagina*50)}
                if q.get("tienda"):
                    filtros["tienda_id"] = "eq." + uuid(q["tienda"][0])
                if q.get("jornada"):
                    filtros["jornada"] = "eq." + datetime.strptime(q["jornada"][0], "%Y-%m-%d").date().isoformat()
                if q.get("alertas"):
                    filtros["resultado->>estado"] = "neq.OK"
                filas = CENTRAL.tabla("analisis", token, filtros)
                return self._json(200, {"items": [CENTRAL.item(f) for f in filas], "mas": len(filas)==50})
            partes = ruta.strip("/").split("/")
            if len(partes) in (3,4) and partes[:2] == ["api", "analisis"]:
                fila = CENTRAL.analisis(token, partes[2])
                if metodo == "GET" and len(partes)==4 and partes[3] in ("original", "anotada"):
                    path = fila[partes[3] + "_path"]
                    if not path:
                        raise ErrorAPI(404, "Esta imagen no esta disponible.")
                    contenido = CENTRAL.archivo(token, path)
                    self.send_response(200)
                    self.send_header("Content-Type", "image/jpeg")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", str(len(contenido)))
                    self.end_headers()
                    return self.wfile.write(contenido)
                if metodo == "DELETE" and len(partes)==3:
                    rol = CENTRAL.miembro(token, usuario["id"], fila["tienda_id"])
                    if usuario["id"] != fila["usuario_id"] and rol != "admin":
                        raise ErrorAPI(403, "Solo el autor o administrador puede eliminar este analisis.")
                    rutas = [fila[k] for k in ("original_path","anotada_path") if fila[k]]
                    if rutas:
                        CENTRAL.pedir("/storage/v1/object/visualshelf", token, "DELETE", {"prefixes": rutas})
                    CENTRAL.tabla("analisis", token, {"id": "eq."+fila["id"]}, "DELETE")
                    return self._json(200, {"ok": True})
            if ruta == "/api/analizar" and metodo == "POST":
                payload = self.cuerpo()
                tienda = uuid(payload.get("tienda_id"))
                CENTRAL.miembro(token, usuario["id"], tienda)
                identificador = uuid(payload.get("id"))
                jornada = datetime.strptime(payload.get("jornada", ""), "%Y-%m-%d").date().isoformat()
                existente = CENTRAL.tabla("analisis", token, {"id": "eq."+identificador, "select": "*,tiendas(nombre)"})
                if existente:
                    if existente[0]["estado_proceso"] == "completo":
                        return self._json(200, CENTRAL.item(existente[0]))
                    if existente[0]["estado_proceso"] == "error":
                        raise ErrorAPI(422, "El intento anterior fallo. Pulsa Analizar nuevamente para un intento nuevo.")
                    raise ErrorAPI(409, "Esta foto ya se esta procesando. Espera antes de reintentar.")
                gondola = str(payload.get("gondola", "")).strip()[:100]
                if gondola:
                    CENTRAL.tabla("gondolas", token, {"on_conflict":"tienda_id,codigo"}, "POST",
                                  {"tienda_id":tienda,"codigo":gondola}, "resolution=ignore-duplicates")
                registro = {"id": identificador, "tienda_id": tienda, "usuario_id": usuario["id"], "jornada": jornada,
                            "gondola": gondola, "modelo_version": ESTADO.get("modelo_version")}
                CENTRAL.tabla("analisis", token, metodo="POST", datos=registro)
                try:
                    resultado = analizar(payload)
                    original, _ = decodificar_imagen(payload["imagen"])
                    original = a_data_url(cv2.cvtColor(original, cv2.COLOR_BGR2RGB), lado=LADO_MAX)
                    prefijo = f"{tienda}/{usuario['id']}/{identificador}"
                    for nombre, imagen in (("original",original),("anotada",resultado.pop("imagen_anotada"))):
                        if not imagen:
                            raise RuntimeError("No se pudo generar la imagen")
                        path = f"{prefijo}/{nombre}.jpg"
                        CENTRAL.archivo(token, path, "POST", base64.b64decode(imagen.split(",",1)[1]))
                        registro[nombre+"_path"] = path
                    resultado["peso"] = min(MAX_BYTES, max(0,int(payload.get("peso",0))))
                    registro.update(resultado=resultado,estado_proceso="completo")
                    filas = CENTRAL.tabla("analisis", token, {"id":"eq."+identificador}, "PATCH", registro, "return=representation")
                    respuesta = CENTRAL.item(filas[0])
                except Exception:
                    try:
                        rutas = [registro[k] for k in ("original_path","anotada_path") if registro.get(k)]
                        if rutas:
                            CENTRAL.pedir("/storage/v1/object/visualshelf", token, "DELETE", {"prefixes":rutas})
                        CENTRAL.tabla("analisis", token, {"id":"eq."+identificador}, "PATCH", {"estado_proceso":"error"})
                    except ErrorAPI:
                        pass
                    raise
                return self._json(200,respuesta)
            if ruta == "/api/importar" and metodo == "POST":
                payload = self.cuerpo()
                tienda = uuid(payload.get("tienda_id"))
                CENTRAL.miembro(token, usuario["id"], tienda)
                items = payload.get("items")
                if not isinstance(items,list) or len(items)>300:
                    raise ErrorAPI(400,"Importa como maximo 300 registros por lote.")
                registros = []
                from uuid import uuid5, NAMESPACE_URL
                for item in items:
                    if not isinstance(item,dict) or not item.get("id"):
                        raise ErrorAPI(400,"Historial invalido.")
                    resultado = {k:item.get(k) for k in ("nombre","stock_pct","productos","huecos","filas","umbral_pct","confianza","tiempo_s","motivos")}
                    resultado["nombre"] = str(resultado["nombre"] or "Importado")[:200]
                    resultado["estado"] = item.get("estado")
                    if resultado["estado"] not in ("OK","ALERTA_REPONER","REVISION_MANUAL"):
                        raise ErrorAPI(400,"Estado importado invalido.")
                    if resultado["stock_pct"] is not None and (isinstance(resultado["stock_pct"],bool) or not isinstance(resultado["stock_pct"],(int,float)) or not 0<=resultado["stock_pct"]<=100):
                        raise ErrorAPI(400,"Stock importado invalido.")
                    registros.append({"id":str(uuid5(NAMESPACE_URL,usuario["id"]+":"+str(item["id"]))), "usuario_id":usuario["id"],
                        "tienda_id":tienda,"jornada":datetime.strptime(item.get("jornada", ""),"%Y-%m-%d").date().isoformat(),
                        "origen":"importado","estado_proceso":"completo","resultado":resultado})
                if registros:
                    CENTRAL.tabla("analisis", token, {"on_conflict":"id"}, "POST", registros,"resolution=ignore-duplicates")
                return self._json(200,{"ok":True})
            raise ErrorAPI(404,"Ruta no encontrada.")
        except ErrorAPI as error:
            return self._json(error.estado, {"error":str(error)})
        except (ValueError,KeyError,TypeError):
            return self._json(400,{"error":"Datos invalidos. Revisa la imagen, fecha e identificadores."})
        except Exception:
            traceback.print_exc()
            return self._json(500,{"error":"No se pudo completar la operacion. Intenta nuevamente."})

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
        if ruta.startswith("/api/"):
            return self.api("GET")
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
        return self.api("POST")

    def do_DELETE(self):
        return self.api("DELETE")


def main():
    ap = argparse.ArgumentParser(description="VisualShelf — app web del detector de huecos en góndolas")
    ap.add_argument("--modelo", default=os.environ.get("MODELO", str(AQUI / "best.pt")))
    ap.add_argument("--parametros", default=os.environ.get("PARAMETROS", str(AQUI / "parametros_v4.json")))
    ap.add_argument("--puerto", type=int, default=int(os.environ.get("PORT", 7860)))
    ap.add_argument("--host", default=os.environ.get("HOST", "0.0.0.0"))
    a = ap.parse_args()
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
    if Path(a.modelo).is_file():
        with open(a.modelo,"rb") as pesos:
            ESTADO["modelo_version"] = hashlib.file_digest(pesos,"sha256").hexdigest()
    srv = ThreadingHTTPServer((a.host, a.puerto), Manejador)
    print(f"VisualShelf listo en http://127.0.0.1:{a.puerto}  (Ctrl+C para detener)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass



if __name__ == "__main__":
    main()
