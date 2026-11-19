const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const nodos = new Map();
const eventosDocumento = new Map();
const nodo = selector => {
  if (!nodos.has(selector)) nodos.set(selector, {innerHTML:'',textContent:'',value:'',hidden:false,checked:false,
    eventos:new Map(), atributos:new Map(),
    addEventListener(evento,accion) { this.eventos.set(evento,accion); },
    setAttribute(nombre,valor) { this.atributos.set(nombre,valor); }});
  return nodos.get(selector);
};
const contexto = vm.createContext({
  document: {querySelector:nodo, querySelectorAll:()=>[], addEventListener:(evento,accion)=>eventosDocumento.set(evento,accion)},
  window:{}, URLSearchParams, console, setTimeout, clearTimeout,
});
vm.runInContext(fs.readFileSync('static/central.js','utf8'),contexto);
vm.runInContext(fs.readFileSync('static/app.js','utf8'),contexto);
const ejecutar = texto => vm.runInContext(texto,contexto);

(async () => {
  ejecutar('pintarTiendas([{id:"abc",nombre:"<Tienda>"}], "abc")');
  assert.match(nodo('#tienda').innerHTML, /&lt;Tienda&gt;/);
  assert.match(nodo('#tienda').innerHTML, /value="abc"/);
  assert.equal(nodo('#tienda').value,'abc');
  ejecutar('estado.historial=[{tienda_id:"abc",tienda:"Nombre",jornada:"2026-11-18"}];');
  nodo('#filtrar-hist').checked=true;
  nodo('#fecha').value='2026-11-18';
  assert.equal(ejecutar('itemsFiltrados().length'),1);
  assert.match(ejecutar('csvDe([{nombre:"=HYPERLINK(1)",motivos:[]}])'), /'=HYPERLINK/);
  ejecutar('resumenCentral=[{tienda_id:"abc",tienda:"<Tienda>",fotos:120,reabastecer:7,revision:3,stock_pct:60}]; pintarResumen(); pintarContadorAlertas();');
  assert.match(nodo('#tabla-tiendas').innerHTML,/&lt;Tienda&gt;/);
  assert.match(nodo('#resumen-kpis').innerHTML,/120/);
  assert.equal(nodo('#nav-alertas').textContent,7);
  ejecutar('clienteAuth={auth:{getSession:async()=>({data:{session:{access_token:"token"}}}),signOut:async()=>{}}}');
  contexto.fetch=async (ruta,opciones) => {
    assert.equal(opciones.headers.Authorization,'Bearer token');
    return {ok:false,status:403,json:async()=>({error:'Sin permiso'})};
  };
  await assert.rejects(ejecutar('api("api/analisis")'),e=>e.status===403);
  ejecutar('clienteAuth.auth.getSession=async()=>({data:{session:null}})');
  await assert.rejects(ejecutar('api("api/analisis")'),/Inicia sesion/);
  contexto.location={hash:''};
  contexto.fetch=async()=>{throw new Error('Sin conexion de prueba');};
  await eventosDocumento.get('DOMContentLoaded')();
  nodo('#password').type='password';
  const alternar=nodo('#ver-password').eventos.get('click');
  alternar({currentTarget:nodo('#ver-password')});
  assert.equal(nodo('#password').type,'text');
  assert.equal(nodo('#ver-password').atributos.get('aria-pressed'),'true');
  alternar({currentTarget:nodo('#ver-password')});
  assert.equal(nodo('#password').type,'password');
  assert.equal(nodo('#ver-password').atributos.get('aria-label'),'Mostrar contraseña');
  console.log('OK: tiendas, filtros, CSV, resumen completo, token y permisos del cliente');
})().catch(e=>{console.error(e);process.exitCode=1;});
