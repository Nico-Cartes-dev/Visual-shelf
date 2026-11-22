import importlib
import json
import io
from email.message import Message
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from central import Central, ErrorAPI, uuid


class CentralTest(unittest.TestCase):
    def test_uuid_invalido(self):
        for valor in (None, "otro", "../secret"):
            with self.assertRaises(ErrorAPI):
                uuid(valor)

    def test_resultado_no_inyecta_urls_o_campos_del_cliente(self):
        fila = dict(id=str(uuid4()), tienda_id=str(uuid4()), usuario_id=str(uuid4()),
                    jornada="2026-11-18", created_at="2026-11-18T00:00:00Z", origen="yolo",
                    resultado={"nombre":"foto.jpg", "imagen_anotada":'javascript:alert(1)',
                               "estado":"<script>", "stock_pct":"<img>","motivos":"texto"})
        item = Central.item(fila)
        self.assertNotIn("imagen_anotada", item)
        self.assertIsNone(item["stock_pct"])
        self.assertEqual(item["estado"], "REVISION_MANUAL")
        self.assertEqual(item["motivos"], [])

    def test_sin_configuracion_falla_cerrado(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(ErrorAPI) as error:
                Central().config()
            self.assertEqual(error.exception.estado, 503)


class ApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # El contrato HTTP se prueba sin cargar los pesos ni requerir GPU.
        with patch.dict("sys.modules", {"cv2":Mock(),"PIL":Mock(),"motor":Mock()}):
            cls.app = importlib.import_module("app")

    def pedir(self,ruta,metodo="GET",datos=None,token=None):
        manejador = self.app.Manejador.__new__(self.app.Manejador)
        manejador.path = ruta
        manejador.headers = Message()
        cuerpo = json.dumps(datos).encode() if datos is not None else b""
        manejador.rfile = io.BytesIO(cuerpo)
        manejador.headers["Content-Length"] = str(len(cuerpo))
        if token:
            manejador.headers["Authorization"] = "Bearer " + token
        manejador._json = lambda status, dato: (status,dato)
        return manejador.api(metodo)

    def test_sin_login_no_ejecuta_yolo(self):
        with patch.object(self.app,"analizar") as analizar:
            status,_=self.pedir("/api/analizar","POST",{})
            self.assertEqual(status,401)
            analizar.assert_not_called()

    def test_tienda_no_asignada_no_ejecuta_yolo(self):
        with patch.object(self.app,"CENTRAL") as bd,patch.object(self.app,"analizar") as analizar:
            bd.usuario.return_value={"id":str(uuid4())}
            bd.miembro.side_effect=ErrorAPI(403,"Sin acceso")
            status,_=self.pedir("/api/analizar","POST",{"tienda_id":str(uuid4())},"token")
            self.assertEqual(status,403)
            analizar.assert_not_called()

    def test_reintento_devuelve_resultado_sin_repetir_yolo(self):
        identificador=str(uuid4())
        fila={"id":identificador,"estado_proceso":"completo"}
        with patch.object(self.app,"CENTRAL") as bd,patch.object(self.app,"analizar") as analizar:
            bd.usuario.return_value={"id":str(uuid4())}
            bd.tabla.return_value=[fila]
            bd.item.return_value={"id":identificador}
            status,dato=self.pedir("/api/analizar","POST",{"tienda_id":str(uuid4()),"id":identificador,"jornada":"2026-11-18"},"token")
            self.assertEqual(status,200)
            self.assertEqual(dato["id"],identificador)
            analizar.assert_not_called()

    def test_delete_ajeno_rechazado(self):
        with patch.object(self.app,"CENTRAL") as bd:
            bd.usuario.return_value={"id":str(uuid4())}
            bd.analisis.return_value={"id":str(uuid4()),"usuario_id":str(uuid4()),"tienda_id":str(uuid4())}
            bd.miembro.return_value="operador"
            status,_=self.pedir("/api/analisis/"+str(uuid4()),"DELETE",token="token")
            self.assertEqual(status,403)
            bd.archivo.assert_not_called()

    def test_guarda_con_autor_verificado_y_fotos_privadas(self):
        autor,tienda,identificador = (str(uuid4()) for _ in range(3))
        registro = {}
        def tabla(nombre,token,filtros=None,metodo="GET",datos=None,prefer=None):
            if metodo == "GET": return []
            if metodo == "POST": registro.update(datos)
            if metodo == "PATCH":
                registro.update(datos)
                return [{**registro,"created_at":"2026-11-18T00:00:00Z","origen":"yolo"}]
        with patch.object(self.app,"CENTRAL") as bd, patch.object(self.app,"analizar") as analizar, \
                patch.object(self.app,"decodificar_imagen",return_value=(Mock(),None)), \
                patch.object(self.app,"a_data_url",return_value="data:image/jpeg;base64,aW1hZ2Vu"):
            bd.usuario.return_value={"id":autor}
            bd.tabla.side_effect=tabla
            bd.item.side_effect=Central.item
            analizar.return_value={"nombre":"foto.jpg","estado":"OK","stock_pct":80,
                                   "imagen_anotada":"data:image/jpeg;base64,aW1hZ2Vu"}
            status,_=self.pedir("/api/analizar","POST",{"tienda_id":tienda,"id":identificador,
                "jornada":"2026-11-18","usuario_id":"impostor","imagen":"foto"},"token")
            self.assertEqual(status,200)
            self.assertEqual(registro["usuario_id"],autor)
            self.assertEqual(registro["estado_proceso"],"completo")
            self.assertEqual(bd.archivo.call_count,2)
            self.assertEqual(registro["original_path"],f"{tienda}/{autor}/{identificador}/original.jpg")

    def test_motor_ocupado_responde_429(self):
        with patch.dict(self.app.ESTADO,{"modelo_ok":True}), \
                patch.object(self.app,"decodificar_imagen",return_value=(Mock(),None)):
            self.app.CANDADO.acquire()
            try:
                with self.assertRaises(ErrorAPI) as error:
                    self.app.analizar({"confianza":.35,"umbral":30,"imagen":"foto"})
                self.assertEqual(error.exception.estado,429)
            finally:
                self.app.CANDADO.release()


if __name__ == "__main__":
    unittest.main()
