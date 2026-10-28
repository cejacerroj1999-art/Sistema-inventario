# Cambio a usuario y contraseña

Para Héctor: ya ejecutaste 001_schema.sql y registraste el primer administrador.

1. Conserva tus claves de Supabase y GitHub.
2. En Supabase SQL Editor pega y ejecuta el contenido completo de `sql/003_acceso_local.sql`. **No ejecutes otra vez 001_schema.sql.**
3. Reemplaza los archivos de la aplicación por esta versión.
4. Elimina `[auth]` y los valores de Google de `.streamlit/secrets.toml`. Añade al nivel principal:

```toml
COOKIE_SECURE = false
SESSION_COOKIE_NAME = "inventario_sesion"
```

Usa `COOKIE_SECURE = true` cuando publiques con HTTPS; false es para HTTP local.

5. En una terminal dentro de la carpeta `inventario`, ejecuta:

```bash
python -m pip install -r requirements.txt
python scripts/configurar_acceso.py
```

El script pedirá el UUID del administrador que ya tienes (lo copias de Table Editor → usuarios → id), un nombre de acceso y una contraseña. No necesitas Google. No compartas la contraseña ni tus claves.

6. Inicia la aplicación:

```bash
streamlit run app.py
```

Entra con el usuario y contraseña recién definidos. Desde Usuarios puedes crear y habilitar al bodeguero y los vendedores. El correo es opcional y sólo de contacto.

La sesión dura hasta 30 días, salvo cierre de sesión, revocación o eliminación de cookies. El historial y el inventario existentes se conservan. Lee README para los límites y las pruebas pendientes antes de usarlo con inventario real.
