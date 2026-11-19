---
title: VisualShelf
emoji: 🛒
colorFrom: blue
colorTo: yellow
sdk: docker
app_port: 7860
pinned: false
---

# VisualShelf - analisis de gondolas

Aplicacion web para detectar productos y estimar ocupacion de gondolas con YOLO.
Incluye login, permisos por tienda, historial compartido, alertas, CSV y fotos
privadas en Supabase. Las preferencias de analisis permanecen en el navegador.

## Ejecutar

Requiere Python 3.11, dependencias y el archivo `best.pt` junto a `app.py`:

```powershell
python -m pip install -r requirements.txt
./iniciar.ps1
```

Abre http://127.0.0.1:7860. Las cuentas y sus tiendas se habilitan desde Supabase
Dashboard; una cuenta sin asignaciones no tiene acceso a datos de tiendas.

Consulta [CENTRALIZACION.md](CENTRALIZACION.md) para configurar usuarios,
permisos, recuperacion de acceso, Docker, publicacion y pruebas.

## Archivos

| Archivo | Funcion |
|---|---|
| `app.py` | Servidor y API autenticada; ejecuta y guarda analisis. |
| `central.py` | Consultas a Auth, PostgreSQL y Storage con token de usuario. |
| `motor.py` | Deteccion y calculo de stock del notebook V4.1b. |
| `static/` | Interfaz, login y consultas al historial central. |
| `supabase/schema.sql` | Esquema para un proyecto nuevo y politicas RLS. |
| `supabase/test_permisos.sql` | Prueba de aislamiento en PostgreSQL con rollback. |
| `iniciar.ps1` | Arranque en Windows con configuracion publica. |
| `entrenar.py` | Ajuste del modelo desde fotos y etiquetas YOLO locales. |
| `ENTRENAMIENTO.md` | Instrucciones de entrenamiento. |

## Comprobaciones

```powershell
python -m unittest test_central test_entrenar -v
node test_frontend.cjs
```

No se necesita una clave service_role para ejecutar la app. El archivo `.env`
no se carga automaticamente: el host debe establecer las variables de entorno.
El notebook antiguo de Colab requiere configurar esas variables antes de usarlo
con esta version; los enlaces publicos deben usar HTTPS y las URLs de Auth correctas.
