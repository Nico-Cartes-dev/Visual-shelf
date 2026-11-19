-- Prueba real de permisos. Todos los datos de prueba se revierten al terminar.
begin;
insert into auth.users(id,email) values
 ('11111111-1111-4111-8111-111111111111','vs-test-a@example.invalid'),
 ('22222222-2222-4222-8222-222222222222','vs-test-b@example.invalid');
insert into public.tiendas(id,nombre) values
 ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa','TEST tienda A'),
 ('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb','TEST tienda B');
insert into public.usuarios_tiendas(usuario_id,tienda_id) values
 ('11111111-1111-4111-8111-111111111111','aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'),
 ('22222222-2222-4222-8222-222222222222','bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb');
insert into public.analisis(id,tienda_id,usuario_id,jornada,estado_proceso,resultado) values
 ('cccccccc-cccc-4ccc-8ccc-cccccccccccc','aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa','11111111-1111-4111-8111-111111111111',current_date,'completo','{"estado":"OK","stock_pct":80}'),
 ('dddddddd-dddd-4ddd-8ddd-dddddddddddd','bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb','22222222-2222-4222-8222-222222222222',current_date,'completo','{"estado":"ALERTA_REPONER","stock_pct":10}');
insert into storage.objects(bucket_id,name) values
 ('visualshelf','aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/11111111-1111-4111-8111-111111111111/test/original.jpg'),
 ('visualshelf','bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb/22222222-2222-4222-8222-222222222222/test/original.jpg');
set local role authenticated;
select set_config('request.jwt.claims','{"sub":"11111111-1111-4111-8111-111111111111","role":"authenticated"}',true);
do $$ begin
 if (select count(*) from public.tiendas) <> 1 then raise exception 'A ve otra tienda'; end if;
 if (select count(*) from public.analisis) <> 1 then raise exception 'A ve otro analisis'; end if;
 if (select count(*) from storage.objects where bucket_id='visualshelf') <> 1 then raise exception 'A ve fotos ajenas'; end if;
 if jsonb_array_length(public.resumen_visualshelf()) <> 1 then raise exception 'Resumen filtra mal'; end if;
 begin
  insert into public.analisis(id,tienda_id,usuario_id,jornada) values(gen_random_uuid(),'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb','11111111-1111-4111-8111-111111111111',current_date);
  raise exception 'A pudo escribir en B';
 exception when insufficient_privilege then null; end;
 begin
  insert into public.usuarios_tiendas(usuario_id,tienda_id,rol) values('11111111-1111-4111-8111-111111111111','bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb','admin');
  raise exception 'A pudo elevar permisos';
 exception when insufficient_privilege then null; end;
 begin
  insert into storage.objects(bucket_id,name) values('visualshelf','bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb/11111111-1111-4111-8111-111111111111/forbidden.jpg');
  raise exception 'A pudo subir foto a B';
 exception when insufficient_privilege then null; end;
 delete from public.analisis where id='dddddddd-dddd-4ddd-8ddd-dddddddddddd';
 if found then raise exception 'A pudo eliminar B'; end if;
end $$;
select set_config('request.jwt.claims','{"sub":"22222222-2222-4222-8222-222222222222","role":"authenticated"}',true);
do $$ begin
 if (select count(*) from public.analisis) <> 1 or (select resultado->>'estado' from public.analisis) <> 'ALERTA_REPONER' then raise exception 'B no esta aislado'; end if;
end $$;
set local role anon;
do $$ begin
 begin
  perform * from public.analisis;
  raise exception 'Anon tiene acceso';
 exception when insufficient_privilege then null; end;
end $$;
reset role;
select 'OK: tiendas, analisis, Storage, resumen y roles aislados' as resultado;
rollback;
