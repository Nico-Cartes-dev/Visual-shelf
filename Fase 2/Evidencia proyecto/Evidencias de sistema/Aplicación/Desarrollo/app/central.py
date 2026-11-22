"""Acceso a Supabase con el token del usuario: las consultas respetan RLS."""
import json
import os
import math
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, quote
from urllib.request import Request, urlopen
from uuid import UUID


class ErrorAPI(Exception):
    def __init__(self, estado, mensaje):
        self.estado = estado
        super().__init__(mensaje)


def uuid(valor):
    try:
        return str(UUID(str(valor)))
    except (ValueError, TypeError, AttributeError):
        raise ErrorAPI(400, "Identificador invalido") from None


class Central:
    def __init__(self):
        self.url = os.environ.get("SUPABASE_URL", "").rstrip("/")
        self.key = os.environ.get("SUPABASE_PUBLISHABLE_KEY", "")

    def config(self):
        if not self.url.startswith("https://") or not self.key:
            raise ErrorAPI(503, "Configura SUPABASE_URL y SUPABASE_PUBLISHABLE_KEY en el servidor.")
        return {"url": self.url, "key": self.key}

    def pedir(self, ruta, token, metodo="GET", datos=None, tipo="application/json", prefer=None):
        self.config()
        if not token:
            raise ErrorAPI(401, "Inicia sesion para continuar.")
        cuerpo = datos if isinstance(datos, bytes) else (json.dumps(datos).encode() if datos is not None else None)
        headers = {"apikey": self.key, "Authorization": "Bearer " + token, "Content-Type": tipo}
        if prefer:
            headers["Prefer"] = prefer
        try:
            with urlopen(Request(self.url + ruta, data=cuerpo, headers=headers, method=metodo), timeout=30) as r:
                contenido = r.read()
                return json.loads(contenido) if contenido and "json" in r.headers.get("Content-Type", "") else contenido
        except HTTPError as error:
            mensajes = {401: "Sesion vencida. Vuelve a iniciar sesion.", 403: "No tienes permiso para esta operacion.",
                        409: "El registro ya existe o esta siendo procesado."}
            raise ErrorAPI(error.code if error.code in mensajes else 502,
                           mensajes.get(error.code, "Supabase no pudo completar la operacion.")) from None
        except (URLError, TimeoutError):
            raise ErrorAPI(503, "No se pudo conectar con la base central. Intenta nuevamente.") from None

    def tabla(self, tabla, token, filtros=None, metodo="GET", datos=None, prefer=None):
        return self.pedir("/rest/v1/" + tabla + ("?" + urlencode(filtros) if filtros else ""),
                          token, metodo, datos, prefer=prefer)

    def usuario(self, token):
        usuario = self.pedir("/auth/v1/user", token)
        if not isinstance(usuario, dict) or not usuario.get("id"):
            raise ErrorAPI(401, "Sesion invalida.")
        return usuario

    def tiendas(self, token):
        return self.tabla("tiendas", token, {"select": "id,nombre", "order": "nombre"})

    def miembro(self, token, usuario_id, tienda_id):
        filas = self.tabla("usuarios_tiendas", token, {"select": "rol", "usuario_id": "eq." + usuario_id,
                                                       "tienda_id": "eq." + uuid(tienda_id)})
        if not filas:
            raise ErrorAPI(403, "No tienes acceso a esta tienda.")
        return filas[0]["rol"]

    def analisis(self, token, analisis_id):
        filas = self.tabla("analisis", token, {"select": "*", "id": "eq." + uuid(analisis_id)})
        if not filas:
            raise ErrorAPI(404, "Analisis no encontrado.")
        return filas[0]

    def archivo(self, token, ruta, metodo="GET", datos=None):
        return self.pedir("/storage/v1/object/" + ("authenticated/" if metodo == "GET" else "") +
                          "visualshelf/" + quote(ruta, safe="/"), token, metodo, datos, tipo="image/jpeg")

    @staticmethod
    def item(fila):
        dato = fila["resultado"]
        # Solo campos conocidos; nunca URLs o HTML guardados por otro cliente.
        resultado = {k: v if isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) else None
                     for k in ("stock_pct","productos","huecos","filas","umbral_pct","confianza","tiempo_s","peso")
                     for v in [dato.get(k)]}
        resultado.update(nombre=str(dato.get("nombre") or "Imagen")[:200],
                         estado=dato.get("estado") if dato.get("estado") in ("OK","ALERTA_REPONER","REVISION_MANUAL") else "REVISION_MANUAL",
                         motivos=[str(m)[:500] for m in dato.get("motivos",[])[:20]] if isinstance(dato.get("motivos"),list) else [])
        return {**resultado, "id": fila["id"], "tienda_id": fila["tienda_id"],
                "tienda": fila.get("tiendas", {}).get("nombre", ""), "gondola": fila.get("gondola", ""),
                "jornada": fila["jornada"], "fecha": fila["created_at"], "autor_id": fila["usuario_id"],
                "origen": fila["origen"]}
