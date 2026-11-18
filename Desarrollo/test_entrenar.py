"""Pruebas locales: python -m unittest test_entrenar -v"""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import entrenar


class EntrenamientoTest(unittest.TestCase):
    def setUp(self):
        self.temporal = TemporaryDirectory()
        self.addCleanup(self.temporal.cleanup)
        self.raiz = Path(self.temporal.name)
        self.fotos = self.raiz / "fotos"
        self.fotos.mkdir()
        for i in range(5):
            (self.fotos / f"{i}.jpg").write_bytes(b"foto simulada")
            (self.fotos / f"{i}.txt").write_text("0 0.5 0.5 0.2 0.3\n")

    def test_prepara_y_llama_entrenamiento(self):
        pesos = self.raiz / "best.pt"
        pesos.touch()
        salida = self.raiz / "salida"
        modelo = Mock(task="detect", names={0: "producto"})
        modelo.trainer.best = "nuevo/best.pt"
        argumentos = ["entrenar.py", "--fotos", str(self.fotos),
                      "--modelo", str(pesos), "--salida", str(salida)]
        yolo = Mock(return_value=modelo)
        with patch.dict("sys.modules", {"ultralytics": SimpleNamespace(YOLO=yolo)}), \
                patch("sys.argv", argumentos), patch("builtins.print"):
            entrenar.main()
        opciones = modelo.train.call_args.kwargs
        datos = json.loads(Path(opciones["data"]).read_text(encoding="utf-8"))
        self.assertEqual(datos["names"], ["producto"])
        dataset = Path(datos["path"])
        self.assertEqual(len(list((dataset / "images/train").glob("*.jpg"))), 4)
        self.assertEqual(len(list((dataset / "labels/val").glob("*.txt"))), 1)
        self.assertEqual(len(list(self.fotos.glob("*.jpg"))), 5)
        self.assertEqual(opciones["workers"], 0)
        self.assertTrue(pesos.exists())

    def test_rechaza_etiqueta_faltante_antes_de_copiar(self):
        (self.fotos / "0.txt").unlink()
        destino = self.raiz / "dataset"
        with self.assertRaisesRegex(ValueError, "Falta etiqueta"):
            entrenar.preparar(self.fotos, self.fotos, destino, 1)
        self.assertFalse(destino.exists())

    def test_rechaza_valores_invalidos(self):
        for contenido in ("1 0.5 0.5 0.2 0.3", "0 nan 0.5 0.2 0.3",
                          "0 0.5 0.5 0 0.3", "0 0.5 0.5"):
            with self.subTest(contenido=contenido):
                (self.fotos / "0.txt").write_text(contenido)
                with self.assertRaisesRegex(ValueError, "invalida"):
                    entrenar.preparar(self.fotos, self.fotos, self.raiz / "dataset", 1)


if __name__ == "__main__":
    unittest.main()
