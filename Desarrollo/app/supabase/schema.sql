-- Ejecutar una vez en un proyecto Supabase vacio. No contiene cuentas ni claves.
begin;
create table public.perfiles (
 id uuid primary key references auth.users(id) on delete cascade,
 nombre text not null default '' check (length(nombre) <= 150)
);
create table public.tiendas (
 id uuid primary key default gen_random_uuid(),
 nombre text not null unique check (length(nombre) between 1 and 150)
);
create table public.usuarios_tiendas (
 usuario_id uuid not null references auth.users(id) on delete cascade,
 tienda_id uuid not null references public.tiendas(id) on delete cascade,
 rol text not null default 'operador' check (rol in ('admin','operador')),
 primary key(usuario_id, tienda_id)
);
create index usuarios_tiendas_tienda on public.usuarios_tiendas(tienda_id);
create table public.gondolas (
 id uuid primary key default gen_random_uuid(),
 tienda_id uuid not null references public.tiendas(id),
 codigo text not null check(length(codigo) between 1 and 100),
 unique(tienda_id,codigo)
);
create table public.analisis (
 id uuid primary key,
 tienda_id uuid not null references public.tiendas(id),
 usuario_id uuid not null references auth.users(id),
 gondola text not null default '' check(length(gondola) <= 100),
 jornada date not null,
 created_at timestamptz not null default now(),
 estado_proceso text not null default 'procesando' check(estado_proceso in ('procesando','completo','error')),
 origen text not null default 'yolo' check(origen in ('yolo','importado')),
 resultado jsonb not null default '{}'::jsonb check (jsonb_typeof(resultado) = 'object' and octet_length(resultado::text) <= 150000),
 original_path text,
 anotada_path text,
 modelo_version text,
 unique(usuario_id,id),
 constraint resultado_completo_valido check (
  estado_proceso <> 'completo' or (
   resultado ? 'estado' and resultado->>'estado' in ('OK','ALERTA_REPONER','REVISION_MANUAL')
   and (not resultado ? 'stock_pct' or resultado->'stock_pct'='null'::jsonb or
        (jsonb_typeof(resultado->'stock_pct')='number' and (resultado->>'stock_pct')::numeric between 0 and 100))
  )
 )
);
create index analisis_tienda_fecha on public.analisis(tienda_id,created_at desc,id);
create index analisis_usuario on public.analisis(usuario_id);
create index analisis_jornada on public.analisis(jornada);
alter table public.perfiles enable row level security;
alter table public.tiendas enable row level security;
alter table public.usuarios_tiendas enable row level security;
alter table public.gondolas enable row level security;
alter table public.analisis enable row level security;
revoke all on public.perfiles, public.tiendas, public.usuarios_tiendas, public.gondolas, public.analisis from anon, authenticated;
grant select,insert,update on public.perfiles to authenticated;
grant select on public.tiendas, public.usuarios_tiendas to authenticated;
grant select,insert on public.gondolas to authenticated;
grant select,insert,update,delete on public.analisis to authenticated;
create policy perfil_leer on public.perfiles for select to authenticated using(id=(select auth.uid()));
create policy perfil_crear on public.perfiles for insert to authenticated with check(id=(select auth.uid()));
create policy perfil_editar on public.perfiles for update to authenticated using(id=(select auth.uid())) with check(id=(select auth.uid()));
create policy miembros_propios on public.usuarios_tiendas for select to authenticated using(usuario_id=(select auth.uid()));
create policy tiendas_asignadas on public.tiendas for select to authenticated using(exists(select 1 from public.usuarios_tiendas m where m.tienda_id=id and m.usuario_id=(select auth.uid())));
create policy gondolas_leer on public.gondolas for select to authenticated using(exists(select 1 from public.usuarios_tiendas m where m.tienda_id=gondolas.tienda_id and m.usuario_id=(select auth.uid())));
create policy gondolas_crear on public.gondolas for insert to authenticated with check(exists(select 1 from public.usuarios_tiendas m where m.tienda_id=gondolas.tienda_id and m.usuario_id=(select auth.uid())));
create policy analisis_leer on public.analisis for select to authenticated using(exists(select 1 from public.usuarios_tiendas m where m.tienda_id=analisis.tienda_id and m.usuario_id=(select auth.uid())));
create policy analisis_crear on public.analisis for insert to authenticated with check(usuario_id=(select auth.uid()) and exists(select 1 from public.usuarios_tiendas m where m.tienda_id=analisis.tienda_id and m.usuario_id=(select auth.uid())));
create policy analisis_editar on public.analisis for update to authenticated using(usuario_id=(select auth.uid()) and exists(select 1 from public.usuarios_tiendas m where m.tienda_id=analisis.tienda_id and m.usuario_id=(select auth.uid()))) with check(usuario_id=(select auth.uid()) and exists(select 1 from public.usuarios_tiendas m where m.tienda_id=analisis.tienda_id and m.usuario_id=(select auth.uid())));
create policy analisis_eliminar on public.analisis for delete to authenticated using(exists(select 1 from public.usuarios_tiendas m where m.tienda_id=analisis.tienda_id and m.usuario_id=(select auth.uid()) and (m.rol='admin' or analisis.usuario_id=(select auth.uid()))));
insert into storage.buckets(id,name,public,file_size_limit,allowed_mime_types)
values('visualshelf','visualshelf',false,20971520,array['image/jpeg']);
create policy fotos_leer on storage.objects for select to authenticated using(bucket_id='visualshelf' and exists(select 1 from public.usuarios_tiendas m where m.tienda_id::text=(storage.foldername(name))[1] and m.usuario_id=(select auth.uid())));
create policy fotos_crear on storage.objects for insert to authenticated with check(bucket_id='visualshelf' and (storage.foldername(name))[2]=(select auth.uid())::text and exists(select 1 from public.usuarios_tiendas m where m.tienda_id::text=(storage.foldername(name))[1] and m.usuario_id=(select auth.uid())));
create policy fotos_eliminar on storage.objects for delete to authenticated using(bucket_id='visualshelf' and exists(select 1 from public.usuarios_tiendas m where m.tienda_id::text=(storage.foldername(name))[1] and m.usuario_id=(select auth.uid()) and (m.rol='admin' or (storage.foldername(name))[2]=(select auth.uid())::text)));
create function public.resumen_visualshelf() returns jsonb language sql stable security invoker set search_path='' as $$
 select coalesce(jsonb_agg(t),'[]'::jsonb) from (
 select a.tienda_id,t.nombre as tienda,count(*) as fotos,
 avg((a.resultado->>'stock_pct')::numeric) as stock_pct,
 count(*) filter(where a.resultado->>'estado'='ALERTA_REPONER') as reabastecer,
 count(*) filter(where a.resultado->>'estado'='REVISION_MANUAL') as revision,
 max(a.jornada) as ultima_revision
 from public.analisis a join public.tiendas t on t.id=a.tienda_id
 where a.estado_proceso='completo' group by a.tienda_id,t.nombre order by t.nombre
 ) t;
$$;
revoke all on function public.resumen_visualshelf() from public,anon;
grant execute on function public.resumen_visualshelf() to authenticated;
commit;
