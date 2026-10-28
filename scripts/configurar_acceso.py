"""Asigna la primera contraseña a un administrador existente. Ejecutar desde la raíz."""
import getpass
import sys
import tomllib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from supabase import create_client
from access import hash_password, valid_login


def main():
    secrets_path=Path('.streamlit/secrets.toml')
    settings=tomllib.loads(secrets_path.read_text(encoding='utf-8'))
    client=create_client(settings['SUPABASE_URL'],settings['SUPABASE_SERVICE_KEY'])
    actor_id=input('UUID del administrador existente (Table Editor → usuarios → id): ').strip()
    data=client.table('usuarios').select('id,usuario,email,rol,activo').eq('id',actor_id).execute().data
    if not data or data[0]['rol']!='administrador' or not data[0]['activo']:
        raise ValueError('El UUID debe corresponder a un administrador activo ya creado.')
    actor=data[0]
    login=input('Nombre de acceso (por ejemplo hector.admin): ').strip().lower()
    if not valid_login(login):
        raise ValueError('Usa entre 3 y 40 caracteres: a-z, 0-9, punto, guion o guion bajo.')
    password=getpass.getpass('Nueva contraseña (mínimo 10 caracteres): ')
    if password!=getpass.getpass('Repite la contraseña: '):
        raise ValueError('Las contraseñas no coinciden.')
    client.rpc('guardar_usuario_local',dict(p_actor=actor_id,p_target=actor_id,p_nombre=actor['usuario'],
        p_login=login,p_rol=actor['rol'],p_activo=True,p_email=actor.get('email') or '',
        p_hash=hash_password(password))).execute()
    print('Acceso configurado. Ya puedes iniciar sesión con ese usuario y contraseña.')


if __name__=='__main__':
    try:
        main()
    except Exception:
        # No imprimir payloads de RPC ni secretos ante errores del servicio.
        print('No se pudo configurar el acceso. Revisa el UUID, la contraseña, los secretos y que ejecutaste 003_acceso_local.sql.')
        raise SystemExit(1)
