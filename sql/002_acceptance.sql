-- Ejecutar completo en SQL Editor de pruebas; termina en ROLLBACK.
begin;
do $$
declare
 a uuid:=gen_random_uuid(); v uuid:=gen_random_uuid(); b uuid:=gen_random_uuid();
 supplier uuid:=gen_random_uuid(); p uuid:=gen_random_uuid(); doc uuid; sale uuid;
 r jsonb; payload jsonb; balance numeric; avg_cost numeric; failed boolean;
begin
 insert into public.usuarios(id,usuario,email,rol) values
 (a,'Test admin',a::text||'@example.test','administrador'),
 (b,'Test bodega',b::text||'@example.test','bodeguero'),
 (v,'Test venta',v::text||'@example.test','vendedor');
 insert into public.proveedor(id,rut,nombre) values(supplier,supplier::text,'Test proveedor');
 insert into public.productos(id,codigo_de_barras,nombre,tipo,stock,valor_unitario,precio_venta)
 values(p,p::text,'Test producto','Test',10,1000,2000);
 payload:=jsonb_build_object('tipo','factura','numero',gen_random_uuid()::text,'fecha','2026-10-28',
  'proveedor_id',supplier,'archivo_path','Facturas/test.pdf','archivo_url','https://example.test/test',
  'detalle',jsonb_build_array(jsonb_build_object('producto_id',p,'cantidad',20,'costo_unitario',1300,'precio_venta',2000)));
 r:=public.operar(b,gen_random_uuid(),'documento',payload);
 doc:=(r->>'id')::uuid;
 perform public.operar(b,gen_random_uuid(),'aprobar',jsonb_build_object('id',doc));
 select stock,valor_unitario into balance,avg_cost from public.productos where id=p;
 if balance<>30 or avg_cost<>1200 then raise exception 'Fallo promedio ponderado'; end if;
 perform public.operar(b,gen_random_uuid(),'aprobar',jsonb_build_object('id',doc));
 if (select stock from public.productos where id=p)<>30 then raise exception 'Doble entrada'; end if;
 -- Vendedor no puede crear productos.
 failed:=false;
 begin
  perform public.operar(v,gen_random_uuid(),'producto',jsonb_build_object('nombre','No autorizado'));
 exception when others then failed:=true;
 end;
 if not failed then raise exception 'Permisos vendedor incorrectos'; end if;
 -- Una salida sin stock debe revertirse completa y permanecer pendiente.
 payload:=jsonb_build_object('tipo','manual','numero',gen_random_uuid()::text,'fecha','2026-10-28',
  'detalle',jsonb_build_array(jsonb_build_object('producto_id',p,'cantidad',31,'costo_unitario',1200,'precio_venta',2000)));
 r:=public.operar(v,gen_random_uuid(),'documento',payload);
 sale:=(r->>'id')::uuid;
 failed:=false;
 begin
  perform public.operar(v,gen_random_uuid(),'aprobar',jsonb_build_object('id',sale));
 exception when others then failed:=true;
 end;
 if not failed then raise exception 'Se aceptó stock negativo'; end if;
 if (select stock from public.productos where id=p)<>30 then raise exception 'Rollback stock incorrecto'; end if;
 if (select estado from public.documentos where id=sale)<>'pendiente' then raise exception 'Rollback estado incorrecto'; end if;
 raise notice 'OK: promedio ponderado, doble aprobación, permisos y stock insuficiente';
end $$;
rollback;
