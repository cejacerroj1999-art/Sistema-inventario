-- Pruebas opcionales: ejecutar completo en un entorno de prueba, tras 003.
-- Usa credenciales ficticias y termina en ROLLBACK.
begin;
do $$
declare
 a uuid:=gen_random_uuid(); login_name text:='test.'||substr(gen_random_uuid()::text,1,12);
 hash text; sesion jsonb; token text; u jsonb; i integer;
begin
 insert into public.usuarios(id,usuario,rol) values(a,'Admin prueba','administrador');
 hash:=extensions.crypt('ClaveFicticia123!',extensions.gen_salt('bf',12));
 perform public.guardar_usuario_local(a,a,'Admin prueba',login_name,'administrador',true,'',hash);
 for i in 1..5 loop
  if public.iniciar_sesion_local(login_name,'incorrecta') is not null then raise exception 'Aceptó contraseña incorrecta'; end if;
 end loop;
 if public.iniciar_sesion_local(login_name,'ClaveFicticia123!') is not null then raise exception 'No bloqueó al quinto fallo'; end if;
 update public.credenciales set bloqueado_hasta=now()-interval '1 minute' where usuario_id=a;
 sesion:=public.iniciar_sesion_local(login_name,'ClaveFicticia123!');
 token:=sesion->>'token';
 if token is null or length(token)<>64 then raise exception 'Token inválido'; end if;
 u:=public.validar_sesion_local(token);
 if u->>'id' is distinct from a::text then raise exception 'No restauró la sesión'; end if;
 if public.validar_sesion_local(repeat('x',64)) is not null then raise exception 'Aceptó token inventado'; end if;
 perform public.cerrar_sesion_local(token);
 if public.validar_sesion_local(token) is not null then raise exception 'Cookie revocada sigue válida'; end if;
 sesion:=public.iniciar_sesion_local(login_name,'ClaveFicticia123!');
 token:=sesion->>'token';
 perform public.guardar_usuario_local(a,a,'Admin prueba',login_name,'administrador',true,'',hash);
 if public.validar_sesion_local(token) is not null then raise exception 'Cambio de clave no revocó sesiones'; end if;
 if has_table_privilege('service_role','public.credenciales','select') then raise exception 'service_role puede leer hashes'; end if;
 if has_function_privilege('anon','public.iniciar_sesion_local(text,text)','execute') then raise exception 'anon tiene acceso al login'; end if;
 if exists(select 1 from public.historial where usuario_id=a and (coalesce(antes::text,'')||coalesce(despues::text,'')) like '%password_hash%') then
  raise exception 'Se filtró hash en historial';
 end if;
 raise notice 'OK: claves, bloqueo, sesión, cierre, revocación y permisos';
end $$;
rollback;
