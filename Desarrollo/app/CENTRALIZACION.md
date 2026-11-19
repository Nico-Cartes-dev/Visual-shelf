# VisualShelf con acceso e historial compartido

Implementacion: interfaz HTML/JS existente, Supabase Auth, PostgreSQL y Storage
privado. El backend consulta Supabase con el token del usuario; no necesita una
clave secreta ni service_role. El motor de deteccion conserva su comportamiento.

Proyecto configurado: https://supabase.com/dashboard/project/nkdcapusephxjtsvlhbj

## Arranque local

Con Python 3.11 y las dependencias de `requirements.txt` instaladas:

```powershell
./iniciar.ps1
```

Abre http://127.0.0.1:7860. `iniciar.ps1` configura las dos variables publicas
necesarias; para Docker u otro host configura `SUPABASE_URL` y
`SUPABASE_PUBLISHABLE_KEY` con los valores de `.env.example`. Ese archivo es una
referencia: no se carga automaticamente. Las claves publishable son publicas;
la proteccion depende de las sesiones y de las politicas RLS.

## Primer usuario y tiendas

La administracion inicial se realiza en Supabase Dashboard, sin agregar otro
panel de administracion a la app:

1. En Authentication > URL Configuration configura Site URL y Redirect URLs
   con la URL de la app. Para pruebas locales agrega http://127.0.0.1:7860/.
2. Deshabilita el registro publico en los ajustes de Auth. No hay formulario
   de registro en la app y una cuenta sin tiendas asignadas no puede leer datos.
3. En Authentication > Users invita al usuario con su correo real. La app permite
   definir la contraseña desde el enlace de invitacion y recuperar acceso.
   Configura SMTP propio antes de depender del correo para uso real.
4. Crea una fila en `tiendas` desde Table Editor. Copia su UUID y el UUID del
   usuario desde Authentication.
5. Crea una fila en `usuarios_tiendas` con ambos UUID y rol `admin` u `operador`.
   Las asignaciones se gestionan solo desde Dashboard, no desde el cliente.

Los dos roles ven el historial de sus tiendas y pueden analizar. Un operador
elimina sus propios analisis; un administrador elimina cualquiera de su tienda.
No se almacenan contraseñas en tablas de la aplicacion. `perfiles` esta preparado
para el nombre del usuario; el acceso actual muestra el correo verificado.

## Datos y fotos

Cada analisis guarda autor, tienda, codigo opcional de gondola, jornada, fecha de
registro, parametros, resultado y hash SHA-256 del archivo de pesos.
Las gondolas se registran por tienda y codigo al analizar.
Storage guarda JPEG original normalizado y JPEG anotado. El original se orienta
segun EXIF y se reduce a 4000 px; no es una copia byte por byte del archivo subido.
Las fotos se descargan solo al abrir un analisis, mediante API autenticada.

Historial y alertas cargan 50 registros por pagina, con Cargar mas. El resumen y
el contador de alertas consultan el conjunto completo permitido por RLS, sin
depender de las paginas cargadas. CSV exporta los registros cargados.
Actualizar refresca los datos compartidos; no hay suscripcion en tiempo real.

Importar historial local permite transferir los registros de la tienda elegida
cuando su nombre coincide con el nombre antiguo. Pide confirmacion, conserva
los originales locales y evita duplicados por usuario e identificador antiguo.
Los importados se marcan como tales; no se recuperan fotos originales ni se
presenta la fecha del archivo como fecha de ejecucion del analisis.

## Concurrencia y recuperacion

El modelo usa estado global. Un candado evita ejecutar dos inferencias a la vez;
otra peticion recibe HTTP 429 y conserva la foto para reintentar. Mantener un solo
proceso de inferencia por instancia. No aumentar workers del servidor sin revisar
este limite y la memoria del modelo.

Un UUID estable por foto evita repetir inferencia si se perdio la respuesta de un
analisis ya guardado. Un error confirmado permite un intento nuevo. Un registro
que quede `procesando` por reinicio debe revisarse en Dashboard: comprobar que no
hay trabajo activo, limpiar fotos parciales y marcarlo `error` para reintentar.
Si falla Storage, se intenta limpiar las subidas parciales y marcar el error.
Si tambien falla esa limpieza por corte de red, requiere revision manual.

La eliminacion borra primero archivos y despues el registro. Si el segundo paso
falla, reintentar la eliminacion; PostgreSQL y Storage no comparten transaccion.
Una cola persistente queda para cuando las pruebas de carga la justifiquen.

## Publicacion

Construye el Dockerfile de esta carpeta y ejecutalo en un host con salida HTTPS
a Supabase y memoria suficiente para los pesos. Conserva `best.pt` junto a
`app.py` o configura `MODELO`. El `.pt` de entrenamiento no se reemplaza.
Termina HTTPS en el proxy del host, configura limites de peticiones y timeout
segun la latencia medida del modelo. El servidor HTTP de Python es el servidor
actual de la app; no se publica directamente a Internet sin un proxy adecuado.
Actualiza las URLs de Auth al dominio final y prueba el correo de recuperacion.

No se ha contratado ni desplegado un host de inferencia. Debe elegirse antes de
habilitar el uso publico; el proyecto Supabase por si solo no ejecuta YOLO.

## Verificacion

```powershell
python -m unittest test_central test_entrenar -v
node test_frontend.cjs
```

`supabase/test_permisos.sql` prueba en PostgreSQL usuarios de dos tiendas, datos,
Storage, resumen y elevacion de permisos; usa una transaccion con rollback.
`supabase/schema.sql` contiene el esquema inicial para un proyecto nuevo;
no volver a ejecutarlo sobre el proyecto ya configurado.

Antes de publicar falta la prueba con cuentas reales desde dos navegadores,
recuperacion por correo y una imagen real procesada por YOLO. Las pruebas del
backend sustituyen el motor para comprobar permisos sin GPU.
