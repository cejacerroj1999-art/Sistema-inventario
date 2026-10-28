-- Ejecutar una vez en un proyecto nuevo de Supabase. No borra tablas existentes.
begin;
create table public.usuarios (
 id uuid primary key default gen_random_uuid(), usuario text not null,
 email text not null unique check(email=lower(email)),
 rol text not null check(rol in ('administrador','bodeguero','vendedor')),
 activo boolean not null default true
);
create table public.proveedor (
 id uuid primary key default gen_random_uuid(), rut text not null unique,
 nombre text not null, email text, numero text
);
create table public.productos (
 id uuid primary key default gen_random_uuid(), codigo_de_barras text unique,
 nombre text not null check(length(trim(nombre))>0), tipo text not null,
 valor_unitario numeric(18,6) not null default 0 check(valor_unitario>=0),
 stock numeric(18,3) not null default 0 check(stock>=0),
 precio_venta numeric(18,2) not null default 0 check(precio_venta>=0),
 stock_minimo numeric(18,3) not null default 5 check(stock_minimo>=0),
 version integer not null default 1
);
create table public.documentos (
 id uuid primary key default gen_random_uuid(),
 tipo text not null check(tipo in ('factura','boleta','manual')),
 numero text not null, fecha date not null,
 proveedor_id uuid references public.proveedor(id),
 usuario_id uuid not null references public.usuarios(id),
 estado text not null default 'pendiente' check(estado in ('pendiente','aprobado')),
 archivo_url text, archivo_path text, archivo_sha text,
 aprobado_por uuid references public.usuarios(id), aprobado_en timestamptz,
 venta_dia bigint,
 check ((tipo='factura' and proveedor_id is not null) or (tipo<>'factura' and proveedor_id is null)),
 check ((tipo='manual') or (archivo_path is not null and archivo_url is not null))
);
create unique index factura_folio on public.documentos(proveedor_id,numero) where tipo='factura';
create unique index boleta_folio on public.documentos(numero) where tipo='boleta';
-- Esta base supone un solo negocio/emisor de boletas.
create unique index venta_fecha on public.documentos(fecha,venta_dia) where venta_dia is not null;
create table public.documento_detalle (
 id uuid primary key default gen_random_uuid(), documento_id uuid not null references public.documentos(id),
 producto_id uuid not null references public.productos(id),
 cantidad numeric(18,3) not null check(cantidad>0),
 costo_unitario numeric(18,6) not null check(costo_unitario>=0),
 precio_venta numeric(18,2) not null check(precio_venta>=0),
 unique(documento_id,producto_id)
);
create table public.contador_ventas (fecha date primary key, ultimo bigint not null);
create table public.historial (
 id bigint generated always as identity primary key, fecha timestamptz not null default now(),
 tipo text not null, cantidad numeric(18,3), usuario_id uuid not null references public.usuarios(id),
 producto_id uuid references public.productos(id), documento_id uuid references public.documentos(id),
 antes jsonb, despues jsonb
);
create table public.validaciones (
 historial_id bigint primary key references public.historial(id),
 usuario_id uuid not null references public.usuarios(id), fecha timestamptz not null default now()
);
create table public.operaciones (
 id uuid primary key, usuario_id uuid not null references public.usuarios(id),
 accion text not null, datos jsonb not null, resultado jsonb not null
);
create view public.inventario with (security_invoker=true) as
 select id,codigo_de_barras,nombre,tipo,valor_unitario,
 round(valor_unitario*stock,2) as valor_total,stock,precio_venta,stock_minimo,version from public.productos;

-- Única puerta de escritura de la aplicación. Sólo puede invocarla el servidor.
create function public.operar(p_actor uuid,p_operacion uuid,p_accion text,p_datos jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
declare
 rol_actual text; prev public.operaciones; d public.documentos; p public.productos;
 det record; item jsonb; antes jsonb; resultado jsonb; target uuid; n bigint;
 cambio numeric; costo numeric; venta numeric;
begin
 select rol into rol_actual from public.usuarios where id=p_actor and activo;
 if rol_actual is null then raise exception 'Usuario deshabilitado o inexistente'; end if;
 -- Serializar reintentos, incluso desde dos pestañas.
 perform pg_advisory_xact_lock(hashtextextended(p_operacion::text,0));
 select * into prev from public.operaciones where id=p_operacion;
 if found then
   if prev.usuario_id<>p_actor or prev.accion<>p_accion or prev.datos<>p_datos then
     raise exception 'La operación ya existe con otros datos';
   end if;
   return prev.resultado;
 end if;
 if p_accion in ('usuario','proveedor','validar') and rol_actual<>'administrador' then
   raise exception 'Sólo administrador';
 end if;
 if p_accion='producto' then
   if rol_actual not in ('administrador','bodeguero') then raise exception 'Sin permiso'; end if;
   target:=coalesce(nullif(p_datos->>'id','')::uuid,gen_random_uuid());
   select * into p from public.productos where id=target for update;
   antes:=case when found then to_jsonb(p) else null end;
   if antes is not null and p.version<>(p_datos->>'version')::integer then
     raise exception 'Otro usuario modificó el producto. Recargue los datos';
   end if;
   -- Stock y costo no se modifican por esta ruta: usar ajuste o factura.
   insert into public.productos(id,codigo_de_barras,nombre,tipo,precio_venta,stock_minimo)
   values(target,nullif(trim(p_datos->>'codigo_de_barras'),''),trim(p_datos->>'nombre'),
    trim(p_datos->>'tipo'),(p_datos->>'precio_venta')::numeric,(p_datos->>'stock_minimo')::numeric)
   on conflict(id) do update set codigo_de_barras=excluded.codigo_de_barras,nombre=excluded.nombre,
    tipo=excluded.tipo,precio_venta=excluded.precio_venta,stock_minimo=excluded.stock_minimo,
    version=public.productos.version+1;
   insert into public.historial(tipo,usuario_id,producto_id,antes,despues)
    select 'producto',p_actor,id,antes,to_jsonb(x) from public.productos x where id=target;
 elsif p_accion='ajuste' then
   if rol_actual not in ('administrador','bodeguero') then raise exception 'Sin permiso'; end if;
   if length(trim(coalesce(p_datos->>'motivo','')))<3 then raise exception 'Indique motivo'; end if;
   target:=(p_datos->>'producto_id')::uuid;
   select * into strict p from public.productos where id=target for update;
   if p.version<>(p_datos->>'version')::integer then raise exception 'Datos desactualizados'; end if;
   cambio:=(p_datos->>'stock')::numeric-p.stock;
   antes:=to_jsonb(p);
   update public.productos set stock=(p_datos->>'stock')::numeric,version=version+1 where id=target;
   insert into public.historial(tipo,cantidad,usuario_id,producto_id,antes,despues)
    select 'ajuste',cambio,p_actor,id,antes,to_jsonb(x)||jsonb_build_object('motivo',p_datos->>'motivo')
    from public.productos x where id=target;
 elsif p_accion='documento' then
   if (p_datos->>'tipo'='factura' and rol_actual not in ('administrador','bodeguero'))
    or (p_datos->>'tipo' in ('boleta','manual') and rol_actual not in ('administrador','vendedor')) then
    raise exception 'Sin permiso para este documento';
   end if;
   if jsonb_typeof(p_datos->'detalle') is distinct from 'array' then raise exception 'Falta detalle'; end if;
   if jsonb_array_length(p_datos->'detalle')=0 then raise exception 'Detalle vacío'; end if;
   target:=gen_random_uuid();
   insert into public.documentos(id,tipo,numero,fecha,proveedor_id,usuario_id,archivo_url,archivo_path,archivo_sha)
    values(target,p_datos->>'tipo',p_datos->>'numero',(p_datos->>'fecha')::date,
     nullif(p_datos->>'proveedor_id','')::uuid,p_actor,p_datos->>'archivo_url',p_datos->>'archivo_path',p_datos->>'archivo_sha');
   for item in select value from jsonb_array_elements(p_datos->'detalle') loop
    insert into public.documento_detalle(documento_id,producto_id,cantidad,costo_unitario,precio_venta)
     values(target,(item->>'producto_id')::uuid,(item->>'cantidad')::numeric,
      (item->>'costo_unitario')::numeric,(item->>'precio_venta')::numeric);
   end loop;
   insert into public.historial(tipo,usuario_id,documento_id,despues)
    values('documento_pendiente',p_actor,target,p_datos);
 elsif p_accion='aprobar' then
   target:=(p_datos->>'id')::uuid;
   select * into strict d from public.documentos where id=target for update;
   if (d.tipo='factura' and rol_actual not in ('administrador','bodeguero')) or
      (d.tipo<>'factura' and rol_actual not in ('administrador','vendedor')) then raise exception 'Sin permiso'; end if;
   if d.estado='aprobado' then return jsonb_build_object('id',target,'estado','aprobado'); end if;
   -- Orden estable de locks: evita interbloqueos entre documentos concurrentes.
   for det in select * from public.documento_detalle where documento_id=target order by producto_id loop
    select * into strict p from public.productos where id=det.producto_id for update;
    antes:=to_jsonb(p);
    cambio:=case when d.tipo='factura' then det.cantidad else -det.cantidad end;
    if p.stock+cambio<0 then raise exception 'Stock insuficiente: %',p.nombre; end if;
    costo:=p.valor_unitario;
    if d.tipo='factura' then
     if p.codigo_de_barras is null then raise exception 'Falta código de barras: %',p.nombre; end if;
     costo:=(p.stock*p.valor_unitario+det.cantidad*det.costo_unitario)/(p.stock+det.cantidad);
    end if;
    update public.productos set stock=stock+cambio,valor_unitario=costo,version=version+1 where id=p.id;
    insert into public.historial(tipo,cantidad,usuario_id,producto_id,documento_id,antes,despues)
     select case when d.tipo='factura' then 'entrada' else 'salida' end,cambio,p_actor,id,target,antes,to_jsonb(x)
     from public.productos x where id=p.id;
   end loop;
   if d.tipo<>'factura' then
    insert into public.contador_ventas(fecha,ultimo) values(d.fecha,1)
    on conflict(fecha) do update set ultimo=public.contador_ventas.ultimo+1 returning ultimo into n;
   end if;
   update public.documentos set estado='aprobado',aprobado_por=p_actor,aprobado_en=now(),venta_dia=n where id=target;
   insert into public.historial(tipo,usuario_id,documento_id) values('autorizacion',p_actor,target);
 elsif p_accion='usuario' then
   target:=coalesce(nullif(p_datos->>'id','')::uuid,gen_random_uuid());
   -- Serializa modificaciones de administradores para conservar al menos uno activo.
   perform pg_advisory_xact_lock(7832491);
   select to_jsonb(x) into antes from public.usuarios x where id=target;
   insert into public.usuarios(id,usuario,email,rol,activo)
   values(target,p_datos->>'usuario',lower(trim(p_datos->>'email')),p_datos->>'rol',(p_datos->>'activo')::boolean)
   on conflict(id) do update set usuario=excluded.usuario,email=excluded.email,rol=excluded.rol,activo=excluded.activo;
   if not exists(select 1 from public.usuarios where rol='administrador' and activo) then
    raise exception 'Debe existir un administrador activo';
   end if;
   insert into public.historial(tipo,usuario_id,antes,despues)
    select 'usuario',p_actor,antes,to_jsonb(x) from public.usuarios x where id=target;
 elsif p_accion='proveedor' then
   target:=gen_random_uuid();
   insert into public.proveedor(id,rut,nombre,email,numero)
    values(target,p_datos->>'rut',p_datos->>'nombre',p_datos->>'email',p_datos->>'numero');
   insert into public.historial(tipo,usuario_id,despues) values('proveedor',p_actor,p_datos);
 elsif p_accion='validar' then
   insert into public.validaciones(historial_id,usuario_id) values((p_datos->>'id')::bigint,p_actor)
    on conflict(historial_id) do nothing;
   insert into public.historial(tipo,usuario_id,despues) values('validacion',p_actor,p_datos);
 else raise exception 'Acción desconocida';
 end if;
 resultado:=jsonb_build_object('id',target,'ok',true);
 insert into public.operaciones values(p_operacion,p_actor,p_accion,p_datos,resultado);
 return resultado;
end $$;

-- Claves públicas y usuarios de Supabase Auth no tienen acceso a estas tablas.
-- El servidor Streamlit usa service_role y aplica las reglas en operar().
do $$ declare t text; begin
 foreach t in array array['usuarios','proveedor','productos','documentos','documento_detalle','contador_ventas','historial','validaciones','operaciones'] loop
  execute format('alter table public.%I enable row level security',t);
  execute format('revoke all on public.%I from anon, authenticated',t);
  execute format('revoke all on public.%I from service_role',t);
  execute format('grant select on public.%I to service_role',t);
 end loop;
end $$;
revoke all on public.inventario from anon,authenticated;
grant select on public.inventario to service_role;
revoke execute on function public.operar(uuid,uuid,text,jsonb) from public,anon,authenticated;
grant execute on function public.operar(uuid,uuid,text,jsonb) to service_role;
create index on public.documentos(usuario_id);
create index on public.documentos(proveedor_id);
create index on public.documento_detalle(producto_id);
create index on public.historial(usuario_id);
create index on public.historial(producto_id);
create index on public.historial(documento_id);
commit;
