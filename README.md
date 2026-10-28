# Sistema de inventario · Python, Streamlit, Supabase y GitHub

Base funcional para **un negocio y una bodega**, preparada para configurar y probar antes de usar con inventario real. No se ha desplegado ni conectado a cuentas externas. La interfaz está en español y los valores monetarios se expresan en CLP. Python recomendado: 3.12.

## Qué incluye y qué falta

Incluye catálogo, tipos de producto editables, proveedores, tres roles, documentos pendientes, detalle por producto, autorización transaccional, ventas manuales, boletas, costo promedio ponderado, alertas por umbral, historial persistente, validación administrativa, cámara por fotografía, archivos en GitHub privado y descarga desde el servidor.

**Decisión de autenticación:** esta entrega usa Google OIDC con `st.login()`, no usuario/contraseña propios ni Supabase Auth. `usuarios` es el directorio de personas autorizadas y roles. Se valida el correo verificado con Google y se consulta si sigue activo en cada interacción. Si necesitas usuario/clave internos, hay que reemplazar este módulo por Supabase Auth y gestionar correctamente la persistencia y renovación de sus sesiones. No agregues una columna con contraseñas en texto plano ni cifrado reversible.

No incluye OCR ni extracción automática de PDF/XML, emisión tributaria, integración con SII, lotes, vencimientos, devoluciones, anulaciones, múltiples bodegas ni separación de unidades/cajas. El usuario registra las líneas del documento y verifica sus cantidades. La cámara decodifica **una fotografía**, no video continuo. Los detalles pendientes todavía no tienen pantalla de edición/rechazo: revisa antes de guardarlos; un pendiente incorrecto no cambia stock, pero requiere una ampliación del flujo para corregirlo sin intervención técnica. El historial de movimientos es persistente; el carrito de un formulario sin guardar se pierde si recargas o sales.

No es una versión certificada para producción. Hay pruebas locales del cálculo y de similitud; faltan pruebas de integración en tu Supabase, permisos reales, Google, GitHub, cámara y concurrencia. No se garantiza continuidad durante fallas de red, expiración de credenciales o errores del servidor.

## Arquitectura

El navegador muestra la aplicación Streamlit. El proceso Python del servidor recibe las acciones, identifica al usuario mediante OIDC y habla con Supabase y GitHub. Streamlit cumple el papel de interfaz y servidor de aplicación; Supabase aporta PostgreSQL y su API. GitHub guarda el código y, conforme a lo solicitado, los documentos.

Los archivos se suben con la API Contents de GitHub a `Facturas/` y `boletas/`. Se usan nombres derivados del SHA-256 del contenido, evitando colisiones entre nombres originales. Supabase conserva el enlace, la ruta y el SHA del blob de GitHub. La descarga se hace con el token del servidor: los usuarios no necesitan un token propio de GitHub. El enlace web de un repositorio privado sólo es visible para colaboradores autorizados; el botón de descarga de la app sí funciona para sus usuarios.

GitHub y Supabase no comparten transacción. Primero se sube el archivo y luego se registra el documento. Si falla la segunda parte puede quedar un archivo huérfano en GitHub. El reintento reutiliza la ruta por hash. No borres archivos automáticamente tras un timeout: la transacción SQL podría haberse confirmado. Para mayor volumen conviene pasar los documentos a Supabase Storage privado y conservar GitHub para el código, pero esta base mantiene la ubicación que pediste.

## Permisos

| Acción | Administrador | Bodeguero | Vendedor |
|---|---|---|---|
| Gestionar usuarios | Sí | No | No |
| Agregar proveedores | Sí | No | No |
| Listar proveedores | Sí | Sí | No |
| Ver inventario completo y costos | Sí | Sí | No |
| Crear/modificar catálogo y precio | Sí | Sí | No |
| Ajustar stock con motivo | Sí | Sí | No |
| Cargar/autorizar facturas | Sí | Sí | No |
| Registrar venta manual o boleta | Sí | No | Sí |
| Listar/descargar facturas | Sí | Sí | No |
| Listar/descargar boletas | Sí | No | Sí |
| Ver bajo stock | Sí | Sí | Sí |
| Revisar y validar historial | Sí | No | No |

El vendedor consulta el catálogo en su registro de ventas y ve existencias/precios en bajo stock, sin costos. Una autorización de factura o boleta **aplica stock inmediatamente**. La validación del administrador es una revisión posterior: no vuelve a sumar ni restar. No se impide que el mismo bodeguero cargue y autorice una factura, conforme a lo solicitado.

Las reglas de escritura se comprueban también en `operar()`, no sólo ocultando botones. Esa función sólo se concede al rol `service_role`. La clave se guarda en el servidor; la identidad `p_actor` la establece Python, no se toma de un campo del formulario. RLS bloquea a `anon` y `authenticated`, sin políticas públicas. Este diseño **no** usa `auth.uid()` ni sesiones de Supabase Auth: no mezcles sus políticas con este modelo sin rediseñarlo. Las lecturas con `service_role` pueden ver todas las filas, por lo que el filtrado de lecturas por rol es responsabilidad del servidor. No uses esta arquitectura con un frontend que reciba la clave de servicio.

## Tablas y llaves foráneas

Se consolidan facturas, boletas y salidas manuales en `documentos`, con una columna `tipo`. Esto evita repetir lógica transaccional. `documento_detalle` es el detalle de cualquiera de ellos. Si prefieres los nombres físicos `factura`, `boletas`, `factura_detalle`, se puede adaptar el esquema; esta entrega no crea esas tablas por separado.

| Tabla/columna | Referencia | Para qué sirve |
|---|---|---|
| documentos.proveedor_id | proveedor.id | Proveedor de una factura |
| documentos.usuario_id | usuarios.id | Quién cargó el documento |
| documentos.aprobado_por | usuarios.id | Quién autorizó |
| documento_detalle.documento_id | documentos.id | Cabecera del documento |
| documento_detalle.producto_id | productos.id | Producto real del catálogo |
| historial.usuario_id | usuarios.id | Autor del movimiento |
| historial.producto_id | productos.id | Producto afectado, o NULL |
| historial.documento_id | documentos.id | Documento relacionado, o NULL |
| validaciones.historial_id | historial.id | Movimiento revisado |
| validaciones.usuario_id | usuarios.id | Administrador que revisó |

Ejemplo: no guardas el nombre del proveedor como relación. Guardas su UUID en `documentos.proveedor_id`. La FK obliga a que ese UUID exista en `proveedor.id`, y evita eliminar el proveedor si hay facturas que lo usan. Para mostrar el nombre, se hace un JOIN o una consulta relacionada de Supabase. El código usa consultas relacionadas en el detalle de documentos.

**Factura:** el identificador técnico es un UUID y `numero` conserva el folio real como texto. Dos proveedores pueden entregar la factura `123`; por eso se impone `UNIQUE(proveedor_id, numero)` únicamente para facturas. El folio es la identidad comercial dentro de ese proveedor. Si incorporas distintos tipos tributarios, agrega el tipo DTE a la restricción. En boletas se asume un único emisor y folio único global. `venta_dia` es un correlativo separado que comienza en 1 por fecha y se asigna al autorizar tanto boletas como ventas manuales.

**Inventario:** no hay dos copias del stock. `productos` guarda los valores reales y `inventario` es una vista SQL que agrega `valor_total`. Cada lectura muestra los datos actuales de productos. Las nuevas lecturas no requieren sincronizar otra tabla. Otros navegadores requieren pulsar Recargar datos o realizar una interacción para consultar de nuevo; no hay actualización push en tiempo real.

## UUID: cómo se genera

Un UUID es un identificador de 128 bits, habitualmente representado por 36 caracteres con guiones, por ejemplo `2c6e96a4-21d9-4c5c-99f0-05886bcc6014`. El tipo PostgreSQL es `uuid`, no `varchar(36)`. No es una contraseña ni sustituye los permisos.

```sql
id uuid primary key default gen_random_uuid()
```

Cuando insertas una fila sin `id`, PostgreSQL lo genera. Al crear un registro relacionado recuperas ese ID y lo guardas en su FK. También puedes generar un UUID en Python:

```python
from uuid import uuid4
operacion_id = str(uuid4())
```

Aquí se utiliza como clave de idempotencia. Si una petición se reintenta con el mismo UUID y los mismos datos, devuelve el resultado anterior sin repetir el movimiento. Además, el estado aprobado de cada documento evita aplicar dos veces el stock incluso usando otro UUID de operación.

## Costos, stock e historial

El costo es **promedio ponderado por unidades**:

```
costo_nuevo = (stock_actual × costo_actual + cantidad_entrada × costo_compra)
              / (stock_actual + cantidad_entrada)
```

Ejemplo: 10 unidades a $1.000 y una entrada de 20 a $1.300 dejan 30 unidades a $1.200. El valor total es $36.000. Una salida disminuye unidades y conserva el promedio. Una entrada con stock cero toma el nuevo costo. El precio de venta es independiente: se define y modifica en Productos. El detalle de cada documento conserva una copia del costo y del precio registrados.

Define siempre el costo sobre la misma base contable (por ejemplo, neto sin IVA) y la misma unidad física. Esta versión no calcula impuestos ni convierte cajas en unidades. Usa numeric en PostgreSQL para existencias y dinero; el promedio tiene seis decimales y la valoración visible dos.

La autorización bloquea el documento y sus productos, verifica permisos y stock, cambia existencias, registra antes/después y marca aprobado en **una transacción PostgreSQL**. Si falta stock en cualquier línea, se revierte el documento completo. Las salidas no permiten stock negativo. Las ediciones y ajustes usan `version` para detectar datos desactualizados. Las facturas se identifican además por proveedor y folio; los detalles duplicados del mismo producto se rechazan.

El historial está en Supabase, no en `st.session_state`, y persiste al cerrar sesión. Las acciones normales no permiten borrar ni editar movimientos. `service_role` sólo tiene SELECT en las tablas; sus escrituras pasan por la función. Un propietario de la base sigue teniendo poder administrativo: no es un registro legalmente inalterable. Programa respaldos según tu plan de Supabase y prueba restaurarlos.

## Instalación paso a paso

### 1. Crear el repositorio

Crea un repositorio **privado** en GitHub, inicializado con rama `main`. Copia el contenido de esta carpeta a su raíz. Las carpetas `Facturas` y `boletas` se crean cuando la API sube el primer documento. Mantén código, documentos y permisos fuera del acceso público.

Crea un personal access token **fine-grained**, restringido a ese repositorio, con Contents: Read and write. Debe permitir commits a la rama elegida; una regla de protección puede impedirlos. No otorgues permisos de administración. Conserva el token fuera de Git y renueva al expirar. Las subidas crean commits; en aplicaciones de mayor tráfico será conveniente un repositorio de documentos separado o Storage.

### 2. Crear Supabase

Crea un proyecto nuevo. Abre SQL Editor y ejecuta `sql/001_schema.sql` una vez. El script es de instalación, no una migración reutilizable: si ya existen objetos, no lo vuelvas a ejecutar sin revisar su estado. La transacción revierte si falla.

Crea el primer administrador desde SQL Editor, reemplazando el correo por la cuenta Google con la que iniciarás sesión:

```sql
insert into public.usuarios(usuario, email, rol)
values ('Héctor', 'TU-CORREO@gmail.com', 'administrador');
```

Usa minúsculas en el correo. Los demás usuarios se crean desde la app y deben tener cuenta Google verificada. Desactivar una cuenta impide las operaciones posteriores. La aplicación no administra contraseñas de Google ni invita por correo automáticamente.

Obtén la URL del proyecto y una clave **service_role** de las API keys del proyecto. Tiene privilegios elevados: jamás la pongas en código, Git, una URL, JavaScript del navegador ni un mensaje de error al usuario. La clave pública `anon` no funcionará en esta arquitectura por diseño.

### 3. Configurar Google OIDC

En Google Cloud configura una pantalla de consentimiento OAuth y un cliente OAuth de tipo aplicación web. Habilita los usuarios de prueba si el proyecto está en modo testing. Registra exactamente el callback local:

```
http://localhost:8501/oauth2callback
```

Para el despliegue agrega también `https://TU-APP.streamlit.app/oauth2callback` (o el dominio real). Guarda client ID y client secret en los secretos de Streamlit. La app requiere la identidad y el correo verificado; la cuenta debe estar además habilitada en `usuarios`.

### 4. Configurar secretos y ejecutar

En la raíz del proyecto:

```bash
python -m venv .venv
```

Activa el entorno en Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

O en Linux/macOS:

```bash
source .venv/bin/activate
```

Luego:

```bash
pip install -r requirements.txt
```

Copia `.streamlit/secrets.example.toml` como `.streamlit/secrets.toml`, reemplaza todos los valores y genera un `cookie_secret` aleatorio:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

No subas `secrets.toml` a GitHub; `.gitignore` ya lo excluye. No copies comillas ni valores de ejemplo como secretos reales. Ejecuta:

```bash
streamlit run app.py
```

### 5. Desplegar Streamlit

Conecta el repositorio privado en Streamlit Community Cloud u otro servidor que ejecute Python, selecciona `app.py` y configura los secretos en el panel de despliegue. Usa el callback HTTPS real tanto en Google como en `[auth].redirect_uri`. No habilites visualización pública de secretos ni logs sin protección. Para usar desde un celular, abre el dominio HTTPS de la app y autoriza la cámara. `localhost` en el celular identifica al celular, no a tu computador.

La cookie de identidad de `st.login()` mantiene la sesión al recargar y puede persistir hasta 30 días según la documentación; el navegador, la configuración y el vencimiento pueden exigir iniciar sesión otra vez. No se promete persistencia ilimitada ni que borrar cookies mantenga acceso. Cerrar sesión elimina la cookie de la sesión actual; otras pestañas ya autenticadas pueden permanecer abiertas, conforme al comportamiento de Streamlit. La desactivación en `usuarios` se verifica al volver a interactuar.

### 6. Primer uso

1. Entra con el primer administrador y crea los usuarios de bodega y venta.
2. Agrega proveedores.
3. En Productos, escribe el nombre encontrado en una factura y revisa coincidencias. Selecciona el existente si corresponde. Si es otro, créalo con código de barras, tipo, precio y umbral. El código se conserva como texto para no perder ceros.
4. Registra la factura con proveedor, folio, fecha, archivo y productos. El costo de compra va en cada línea.
5. Guarda el documento pendiente. En Documentos revisa el detalle y autoriza. Esto incorpora stock.
6. Para vender, registra una salida manual o una boleta y autoriza el documento correspondiente. **No registres la misma venta por ambos métodos**: este prototipo no enlaza una boleta posterior con una venta manual anterior. Eso duplicaría la rebaja.
7. El administrador revisa Historial y validaciones; todos pueden consultar Bajo stock.

No se fusionan productos automáticamente por nombre: “leche 1 L” y “leche 200 ml” pueden parecerse y son distintos. Se muestran sugerencias para que la persona confirme el producto correcto. Antes de una entrada, completa códigos faltantes desde Productos. Sólo un código principal por producto; múltiples códigos de empaque requieren una tabla adicional.

## Archivos del proyecto

| Archivo | Función |
|---|---|
| app.py | Interfaz, identidad OIDC, navegación y servicios |
| domain.py | Normalización y sugerencias por nombre; cálculo de referencia |
| github_files.py | Carga y descarga privada de documentos |
| sql/001_schema.sql | Esquema, restricciones, permisos y transacciones |
| .streamlit/secrets.example.toml | Configuración de ejemplo sin secretos reales |
| tests/test_domain.py | Pruebas locales de cálculo y similitud |
| sql/002_acceptance.sql | Pruebas transaccionales para SQL Editor, con rollback |

## Validación antes de uso real

Ejecuta las pruebas locales desde la raíz:

```bash
python -m pytest -q
```

Ejecuta `sql/002_acceptance.sql` en SQL Editor de un entorno de prueba tras instalar el esquema. Crea sus datos dentro de una transacción y al final hace ROLLBACK. Verifica costo, doble autorización, stock insuficiente y permisos de vendedor. Nunca omitas el rollback ni lo ejecutes parcialmente.

Prueba además con tres cuentas reales: permisos de cada menú, descarga privada, cámara en Android/iOS, recarga, cierre/reapertura, cuenta desactivada y cierre de sesión. Abre dos sesiones y autoriza simultáneamente un mismo documento: debe haber una sola entrada/salida. Prueba dos ventas que compitan por la última unidad: sólo una debe aprobarse. Simula fallo de GitHub y timeout de Supabase; revisa pendientes y archivos huérfanos antes de volver a registrar.

## Fuentes oficiales consultadas

- Streamlit OIDC, cookies y cierre de sesión: https://docs.streamlit.io/develop/concepts/connections/authentication
- Supabase: funciones, SECURITY DEFINER y permisos: https://supabase.com/docs/guides/database/functions
- GitHub REST Contents: https://docs.github.com/en/rest/repos/contents

Las dependencias están acotadas por versión mayor, pero no constituyen un lock reproducible. Tras validar el despliegue, fija las versiones exactas probadas. No sustituyas una versión de Streamlit sin repetir las comprobaciones de cookies y login.
