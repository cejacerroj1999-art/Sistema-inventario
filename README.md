# Inventario · acceso con usuario y contraseña

Aplicación Python y Streamlit, base PostgreSQL en Supabase y archivos privados en GitHub. Esta versión **no usa Google ni otro proveedor externo de inicio de sesión**. Cada persona entra con un usuario y una contraseña del sistema.

## Si ya instalaste la versión anterior

No vuelvas a ejecutar `001_schema.sql`, no borres las tablas y no vuelvas a crear tu administrador.

1. Reemplaza los archivos Python y `requirements.txt` por los de este paquete.
2. En SQL Editor de Supabase ejecuta **todo el contenido** de `sql/003_acceso_local.sql`. Es una actualización que conserva usuarios, productos, documentos e historial. No pegues el nombre del archivo como consulta.
3. En tu `.streamlit/secrets.toml` conserva Supabase y GitHub. Elimina `[auth]` y todas sus líneas de Google. Añade los valores indicados en el apartado siguiente, **fuera de cualquier sección `[auth]`**.
4. Instala dependencias: `python -m pip install -r requirements.txt`.
5. Copia el UUID de tu administrador existente en Table Editor → usuarios → id.
6. Desde la raíz del proyecto ejecuta `python scripts/configurar_acceso.py`. Pega el UUID, elige el usuario de acceso (ejemplo `hector.admin`) y escribe dos veces su contraseña. La terminal no muestra los caracteres de la contraseña mientras escribes: es normal. Necesita al menos 10 caracteres y un máximo de 72 bytes UTF-8.
7. Ejecuta `streamlit run app.py` y entra con tus nuevas credenciales.

El correo del administrador que creaste antes puede quedarse como contacto; no necesitas tener cuenta de Google. La actualización agrega el campo `login` para el usuario de acceso y mantiene `usuario` como nombre para mostrar. Los demás usuarios existentes quedan sin acceso hasta asignarles un login y una clave desde Usuarios. El primer administrador puede asignárselos.

## Secretos

El archivo de ejemplo es `.streamlit/secrets.example.toml`. Cópialo como `.streamlit/secrets.toml` y completa tus valores reales:

```toml
SUPABASE_URL = "https://TU-PROYECTO.supabase.co"
SUPABASE_SERVICE_KEY = "TU_CLAVE_SERVICE_ROLE"
GITHUB_TOKEN = "TU_TOKEN_GITHUB"
GITHUB_REPO = "tu-usuario/tu-repositorio-privado"
GITHUB_BRANCH = "main"

# False sólo cuando pruebas con HTTP en tu computador.
COOKIE_SECURE = false
SESSION_COOKIE_NAME = "inventario_sesion"
```

En el despliegue HTTPS utiliza **`COOKIE_SECURE = true`**. Si está en true mientras usas HTTP local, el navegador puede rechazar la cookie y perderás persistencia al recargar. El nombre de cookie debe ser diferente para aplicaciones distintas que compartan dominio. Guarda estos mismos valores en Secrets de tu despliegue Streamlit. Nunca subas `secrets.toml`, el token de GitHub ni la clave de servicio a Git; `.gitignore` lo excluye.

Ya no se utilizan `redirect_uri`, `client_id`, `client_secret`, `server_metadata_url` ni `cookie_secret`. No hace falta un secreto de firma propio porque las sesiones usan tokens aleatorios opacos verificados en la base de datos, no JWT generados por esta app.

## Instalación nueva desde cero

1. Crea un repositorio privado GitHub con rama inicial `main` y copia el contenido de esta carpeta en su raíz. Crea un token fine-grained restringido a ese repositorio, con permiso Contents: Read and write. Las protecciones de rama pueden impedir las subidas: verifica que permita los commits del token.
2. Crea un proyecto Supabase nuevo y ejecuta `sql/001_schema.sql` completo en SQL Editor, una sola vez. Luego ejecuta `sql/003_acceso_local.sql` completo.
3. Crea el primer administrador en SQL Editor:

```sql
insert into public.usuarios(usuario,email,rol)
values ('Héctor','tu-correo@example.com','administrador');
```

El correo es opcional después de 003 y no interviene en el login. El UUID se genera automáticamente. No uses como clave el UUID ni la clave de servicio.

4. Instala Python 3.12, crea un entorno con `python -m venv .venv` y actívalo. En PowerShell: `.venv\Scripts\Activate.ps1`. En Linux/macOS: `source .venv/bin/activate`.
5. Ejecuta `python -m pip install -r requirements.txt`.
6. Configura secretos y asigna las credenciales del primer administrador con el script explicado arriba.
7. Ejecuta `streamlit run app.py`.
8. Para publicar, conecta el repositorio privado a tu hosting Streamlit, selecciona `app.py`, copia los secretos y habilita `COOKIE_SECURE = true` en HTTPS. No necesitas configurar callbacks OAuth ni Google Cloud.

## Contraseñas y sesiones

- Las contraseñas se convierten a **hash bcrypt con sal aleatoria y costo 12**. No se almacenan en texto plano, ni como cifrado reversible. El hash se genera en Python y PostgreSQL lo comprueba mediante pgcrypto. La contraseña se envía únicamente al servidor de autenticación mediante HTTPS/TLS; no se guarda en el historial ni en operaciones.
- Los hashes están separados en `credenciales`, que no se muestra en la app. `service_role` no tiene permiso SELECT directo sobre esa tabla; sólo puede llamar las funciones de autenticación autorizadas.
- Cinco intentos incorrectos bloquean esa cuenta durante 15 minutos. El contador está en Supabase, por lo que recargar no lo reinicia. No hay todavía limitador global por IP ni recuperación automática por email. El administrador restablece las claves desde Usuarios; el script local sirve para recuperar el administrador si conservas acceso a los secretos del servidor.
- Tras el login se genera un token aleatorio de 256 bits. Sólo su SHA-256 se guarda en `sesiones`; el token real queda en una cookie del navegador, sin contraseña ni rol. La sesión se comprueba en la base de datos en cada interacción. **No se guarda el token en URLs.**
- La cookie mantiene el acceso al recargar y tiene una duración máxima de **30 días**, con el mismo vencimiento en Supabase. Cerrar sesión revoca el token en la base y elimina la cookie. Si se copia ese mismo token a otra pestaña, también queda inválido al volver a interactuar. Cambiar la contraseña, cambiar el login o desactivar la cuenta revoca sus sesiones.
- No se promete persistencia ilimitada: borrar cookies, usar navegación privada, un proxy que no reenvíe cookies o llegar al vencimiento puede pedir login de nuevo. El carrito sin guardar sigue siendo temporal y puede perderse al recargar.
- La cookie se escribe con un componente JavaScript, con SameSite=Strict y Secure en HTTPS. **No es HttpOnly.** Para un despliegue con requisitos más estrictos, usa un servidor de autenticación o proxy que emita Set-Cookie HttpOnly; esa infraestructura no está incluida. No incrustes contenido HTML/JS de usuarios en la app. Prueba la persistencia en el dominio final y en los celulares reales antes de usarla con ventas.
- La clave `service_role` sigue siendo exclusiva del proceso Python. El navegador nunca la recibe. Las funciones reciben el actor elegido por el servidor después de validar la sesión. Las APIs de estas tablas y funciones están bloqueadas para `anon` y `authenticated`; **esta aplicación no usa Supabase Auth**. No habilites políticas públicas para resolver errores de configuración.

En Usuarios, el administrador elige nombre para mostrar, login único, rol, estado activo y contraseña. El correo es sólo de contacto y opcional. Al editar, dejar vacíos los dos campos de contraseña conserva la actual. Escribir una contraseña nueva restablece la clave y revoca las sesiones anteriores. La cuenta debe permanecer activa y siempre debe quedar al menos un administrador activo.

## Funciones del inventario

| Acción | Administrador | Bodeguero | Vendedor |
|---|---|---|---|
| Gestionar usuarios y restablecer claves | Sí | No | No |
| Agregar proveedores | Sí | No | No |
| Ver proveedores | Sí | Sí | No |
| Ver inventario y costos | Sí | Sí | No |
| Crear/modificar productos y precio | Sí | Sí | No |
| Ajustar stock con motivo | Sí | Sí | No |
| Cargar y autorizar facturas | Sí | Sí | No |
| Venta manual o con boleta | Sí | No | Sí |
| Listar/descargar facturas | Sí | Sí | No |
| Listar/descargar boletas | Sí | No | Sí |
| Consultar bajo stock | Sí | Sí | Sí |
| Revisar y validar historial | Sí | No | No |

El vendedor busca productos por nombre/código al vender. Puede consultar bajo stock sin ver costos. El menú incluye Volver a la página anterior y permanece disponible si falla una sección. Si falla la conexión antes de autenticar, sólo se muestra un error genérico y se permite reintentar; no se muestra inventario sin sesión.

### Documentos y stock

1. El administrador crea proveedores y los productos del catálogo con código de barras, nombre, tipo, precio de venta y umbral de bajo stock.
2. Al escribir un nombre se sugieren coincidencias: confirma si es el mismo producto; el sistema no fusiona automáticamente productos de distinto formato que tengan nombres parecidos.
3. Al registrar una factura selecciona proveedor, folio, fecha, archivo y detalle, indicando cantidad y costo de compra por línea. Los códigos deben estar completos antes de autorizar. El código de barras es texto para conservar ceros iniciales.
4. Guardar crea un pendiente. En Documentos revisa las líneas, marca la confirmación y pulsa Autorizar. El stock y el historial se actualizan en una única transacción. Una aprobación repetida no vuelve a aplicar existencias. Un fallo en cualquier línea revierte todo.
5. Las boletas y salidas manuales siguen el mismo flujo, pero restan stock al autorizar. No se permite stock negativo. **No registres una venta manual y luego su boleta como otra venta independiente**: duplicaría la rebaja. El enlace posterior entre ambas modalidades todavía no está implementado.
6. Validar un movimiento en Historial es una revisión posterior del administrador; no vuelve a cambiar stock.

La carga de PDF/imagen **no extrae automáticamente sus productos**: no incluye OCR ni lector DTE/XML. La cámara decodifica códigos desde una fotografía, no un video continuo. En celular requiere HTTPS y autorización de cámara.

El costo promedio es ponderado por unidades:

```
(stock_actual × costo_actual + cantidad_entrada × costo_compra)
/ (stock_actual + cantidad_entrada)
```

Ejemplo: 10 a $1.000 y una entrada de 20 a $1.300 dejan 30 a $1.200 y valoración de $36.000. Una salida conserva el promedio. El precio de venta se modifica en Productos, independientemente del costo. Define una misma base contable (neta o con IVA) y unidad de medida para todas las entradas. Esta base no calcula impuestos ni convierte cajas a unidades.

### GitHub y archivos

Los archivos se guardan en `Facturas/` y `boletas/`, con nombre derivado de su hash para evitar colisiones. Supabase guarda enlace web, ruta y SHA de GitHub. Un enlace de un repositorio privado requiere acceso de GitHub; el botón Descargar de la app utiliza el token del servidor y no requiere una cuenta GitHub del vendedor.

GitHub y Supabase no comparten transacción. Se carga primero el archivo; si falla el registro en la base puede quedar un archivo huérfano. Al reintentar se reutiliza la misma ruta por hash. No borres automáticamente archivos después de un timeout. Para grandes volúmenes conviene evaluar Supabase Storage, manteniendo GitHub para el código.

## Tablas, UUID y relaciones

| Tabla | Contenido |
|---|---|
| usuarios | UUID, nombre para mostrar, login, contacto opcional, rol y activo |
| credenciales | FK a usuarios, hash bcrypt y contador de intentos |
| sesiones | Hash del token, FK a usuarios, creación y vencimiento |
| proveedor | UUID, RUT, nombre y contacto |
| productos | Catálogo, costo promedio, stock, precio, tipo y umbral |
| inventario | Vista de productos con valor total calculado |
| documentos | Facturas, boletas y salidas manuales, estado y archivo |
| documento_detalle | Relación documento-producto, cantidad y costos/precio históricos |
| historial | Actor, fecha, tipo, cantidad, referencias y valores antes/después |
| validaciones | Administrador que revisó cada movimiento |
| operaciones | Idempotencia de operaciones de inventario; sin contraseñas |

El UUID se genera con `default gen_random_uuid()`. No necesitas escribirlo manualmente. Una FK como `documentos.proveedor_id references proveedor(id)` obliga a que exista ese proveedor. No se guarda su nombre como relación.

El folio real se guarda en `numero`; el UUID es el ID técnico. Las facturas tienen número único **por proveedor**, porque dos proveedores pueden emitir la factura 123. Para boletas se supone un único negocio emisor y folio global único. `venta_dia` es un correlativo separado que empieza en 1 por fecha para salidas manuales y boletas autorizadas. Si agregas diferentes tipos DTE, amplía la clave comercial de factura.

`inventario` es una vista, no una segunda copia del stock: siempre consulta los productos actuales. Cada navegador obtiene nuevos datos al interactuar o pulsar Recargar datos; no hay actualización push en tiempo real. El historial persiste al salir o recargar porque está en Supabase. El dueño de la base sigue teniendo acceso administrativo: no es un registro legalmente inalterable. Configura respaldos y prueba su restauración.

## Pruebas y límites

Ejecuta `python -m pytest -q`. Incluye pruebas del promedio, similitud de nombres, hashing y política de claves, formulario de login, acceso con credenciales incorrectas y logout con transporte de base simulado.

Los scripts SQL opcionales `002_acceptance.sql` y `004_pruebas_acceso.sql` son para un entorno de prueba: ejecútalos completos. Crean datos ficticios dentro de una transacción y terminan en ROLLBACK. El segundo comprueba bloqueo persistente, claves, sesiones, revocación y privilegios. La validación local de sintaxis no sustituye ejecutarlos en tu Supabase.

No se conectó a tu Supabase ni a tu GitHub para esta actualización. Las pruebas de UI utilizan un servidor simulado, no comprueban que el navegador haya escrito la cookie. Faltan comprobaciones reales de Google-free login, persistencia de cookies, cámara, permisos API, archivos, y concurrencia en el hosting final. Antes de usarlo, prueba cuentas de los tres roles, recarga, cierre de sesión, contraseña cambiada, cuenta desactivada y dos ventas que compitan por la última unidad.

La versión sigue siendo una base para configurar y validar: no incluye edición/rechazo de pendientes, OCR, devoluciones, anulaciones, emisión SII, lotes, vencimientos, múltiples bodegas, conversión de unidades ni recuperación por email. No guardes pendientes incorrectos confiando en poder editarlos después: ese flujo requiere una ampliación. Las dependencias tienen límites de versión; tras validar en tu hosting, fija las versiones exactas probadas.

Fuentes de referencia: PostgreSQL pgcrypto https://www.postgresql.org/docs/current/pgcrypto.html; cookies de contexto Streamlit https://docs.streamlit.io/develop/api-reference/caching-and-state/st.context; componente de cookies https://github.com/NathanChen198/streamlit-cookies-controller; funciones Supabase https://supabase.com/docs/guides/database/functions; GitHub Contents https://docs.github.com/en/rest/repos/contents.
