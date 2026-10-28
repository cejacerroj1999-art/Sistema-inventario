-- ACTUALIZACIÓN: ejecutar después de 001_schema.sql. No borra inventario ni usuarios.
begin;
create schema if not exists extensions;
create extension if not exists pgcrypto with schema extensions;
alter table public.usuarios add column if not exists login text;
alter table public.usuarios alter column email drop not null;
create unique index if not exists usuarios_login_unique on public.usuarios(login) where login is not null;
-- Los usuarios existentes quedan sin acceso hasta asignarles un login y una clave.
create table if not exists public.credenciales (
 usuario_id uuid primary key references public.usuarios(id),
 password_hash text not null, intentos integer not null default 0,
 bloqueado_hasta timestamptz
);
create table if not exists public.sesiones (
 token_hash text primary key, usuario_id uuid not null references public.usuarios(id),
 creada timestamptz not null default now(), vence timestamptz not null
);
create index if not exists sesiones_usuario on public.sesiones(usuario_id);
alter table public.credenciales enable row level security;
alter table public.sesiones enable row level security;
revoke all on public.credenciales,public.sesiones from public,anon,authenticated,service_role;

create or replace function public.guardar_usuario_local(
 p_actor uuid,p_target uuid,p_nombre text,p_login text,p_rol text,p_activo boolean,
 p_email text,p_hash text default null
) returns uuid language plpgsql security definer set search_path='' as $$
declare target uuid:=coalesce(p_target,gen_random_uuid()); anterior jsonb;
begin
 perform pg_advisory_xact_lock(7832491);
 if not exists(select 1 from public.usuarios where id=p_actor and activo and rol='administrador') then
  raise exception 'Sólo administrador';
 end if;
 if p_login !~ '^[a-z0-9][a-z0-9_.-]{2,39}$' or length(trim(p_nombre))=0 then
  raise exception 'Usuario: 3 a 40 caracteres, minúsculas, números, punto, guion o guion bajo';
 end if;
 if p_hash is not null and p_hash !~ '^\$2[ab]\$12\$[./A-Za-z0-9]{53}$' then
  raise exception 'Hash bcrypt inválido';
 end if;
 select to_jsonb(u) into anterior from public.usuarios u where id=target for update;
 if not exists(select 1 from public.credenciales where usuario_id=target) and p_hash is null then
  raise exception 'Asigne una contraseña para el nuevo usuario';
 end if;
 insert into public.usuarios(id,usuario,email,rol,activo,login)
 values(target,trim(p_nombre),nullif(lower(trim(p_email)),''),p_rol,p_activo,p_login)
 on conflict(id) do update set usuario=excluded.usuario,email=excluded.email,rol=excluded.rol,
  activo=excluded.activo,login=excluded.login;
 if not exists(select 1 from public.usuarios where activo and rol='administrador') then
  raise exception 'Debe existir al menos un administrador activo';
 end if;
 if p_hash is not null then
  insert into public.credenciales(usuario_id,password_hash) values(target,p_hash)
  on conflict(usuario_id) do update set password_hash=excluded.password_hash,intentos=0,bloqueado_hasta=null;
 end if;
 if p_hash is not null or anterior->>'login' is distinct from p_login or not p_activo then
  delete from public.sesiones where usuario_id=target;
 end if;
 insert into public.historial(tipo,usuario_id,antes,despues)
 select 'usuario',p_actor,anterior,to_jsonb(u)||jsonb_build_object('clave_actualizada',p_hash is not null)
 from public.usuarios u where id=target;
 return target;
end $$;

create or replace function public.iniciar_sesion_local(p_login text,p_password text)
returns jsonb language plpgsql security definer set search_path='' as $$
declare u public.usuarios; c public.credenciales; token text; nuevo_intento integer;
begin
 if length(p_login)>40 or octet_length(p_password)>72 or length(p_password)<1 then return null; end if;
 select * into u from public.usuarios where login=lower(trim(p_login)) and activo;
 if not found then
  -- Trabajo comparable al bcrypt real, sin revelar si existe el usuario.
  perform extensions.crypt(p_password,'$2a$12$abcdefghijklmnopqrstuu');
  return null;
 end if;
 select * into c from public.credenciales where usuario_id=u.id for update;
 if not found then return null; end if;
 if c.bloqueado_hasta>now() then return null; end if;
 if c.password_hash<>extensions.crypt(p_password,c.password_hash) then
  nuevo_intento:=case when c.bloqueado_hasta is not null then 1 else c.intentos+1 end;
  update public.credenciales set intentos=nuevo_intento,
   bloqueado_hasta=case when nuevo_intento>=5 then now()+interval '15 minutes' else null end
   where usuario_id=u.id;
  -- Retornar, no lanzar excepción: preservar el contador de intentos fallidos.
  return null;
 end if;
 update public.credenciales set intentos=0,bloqueado_hasta=null where usuario_id=u.id;
 token:=encode(extensions.gen_random_bytes(32),'hex');
 insert into public.sesiones(token_hash,usuario_id,vence)
 values(encode(extensions.digest(token,'sha256'),'hex'),u.id,now()+interval '30 days');
 delete from public.sesiones where vence<now();
 insert into public.historial(tipo,usuario_id) values('inicio_sesion',u.id);
 return jsonb_build_object('token',token,'usuario_id',u.id);
end $$;

create or replace function public.validar_sesion_local(p_token text)
returns jsonb language sql security definer set search_path='' as $$
 select to_jsonb(u) from public.sesiones s join public.usuarios u on u.id=s.usuario_id
 where length(p_token)=64 and s.token_hash=encode(extensions.digest(p_token,'sha256'),'hex')
 and s.vence>now() and u.activo;
$$;

create or replace function public.cerrar_sesion_local(p_token text)
returns void language plpgsql security definer set search_path='' as $$
declare actor uuid;
begin
 delete from public.sesiones where token_hash=encode(extensions.digest(p_token,'sha256'),'hex')
 returning usuario_id into actor;
 if actor is not null then
  insert into public.historial(tipo,usuario_id) values('cierre_sesion',actor);
 end if;
end $$;

revoke execute on function public.guardar_usuario_local(uuid,uuid,text,text,text,boolean,text,text) from public,anon,authenticated;
revoke execute on function public.iniciar_sesion_local(text,text) from public,anon,authenticated;
revoke execute on function public.validar_sesion_local(text) from public,anon,authenticated;
revoke execute on function public.cerrar_sesion_local(text) from public,anon,authenticated;
grant execute on function public.guardar_usuario_local(uuid,uuid,text,text,text,boolean,text,text) to service_role;
grant execute on function public.iniciar_sesion_local(text,text) to service_role;
grant execute on function public.validar_sesion_local(text) to service_role;
grant execute on function public.cerrar_sesion_local(text) to service_role;
-- Usuarios se gestionan ahora exclusivamente por guardar_usuario_local.
-- operar() conserva la ruta anterior por compatibilidad; sólo el servidor tiene EXECUTE.
commit;
