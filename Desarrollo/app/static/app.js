/* VisualShelf — lógica de la interfaz. Sin librerías externas. */
"use strict";

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const ESTADOS = {
  OK: { clase: "ok", corto: "OK", largo: "Stock adecuado", icono: "i-check" },
  ALERTA_REPONER: { clase: "alerta", corto: "REABASTECER", largo: "Reabastecer", icono: "i-alert" },
  REVISION_MANUAL: { clase: "revision", corto: "REVISIÓN", largo: "Revisión manual", icono: "i-info" },
};
const TITULOS = { resumen: "Resumen", analizar: "Análisis de góndolas", historial: "Historial", alertas: "Alertas", config: "Configuración" };
const CLAVE_HIST = "visualshelf.historial.v1";
const CLAVE_CONF = "visualshelf.config.v1";
const MAX_HIST = 300;

const estado = {
  config: { umbral_pct: 30, confianza: 0.35, max_fotos: 30, tiendas: ["Walmart 2587"], modelo_ok: false },
  pendientes: [],          // archivos seleccionados aún no analizados
  lote: [],                // resultados del último análisis (con imágenes completas)
  indice: 0,
  verDetecciones: true,
  historial: [],           // resultados guardados en este navegador (solo miniatura)
  ocupado: false,
  filaMenu: null,
};

/* ---------------- Almacenamiento local (puede no estar disponible) ---------------- */
function leerLocal(clave, defecto) {
  try { const v = localStorage.getItem(clave); return v ? JSON.parse(v) : defecto; } catch { return defecto; }
}
function guardarLocal(clave, valor) {
  try { localStorage.setItem(clave, JSON.stringify(valor)); return true; } catch { return false; }
}
function guardarHistorial() {
  let h = estado.historial.slice(0, MAX_HIST).map(({ id, nombre, peso, tienda, jornada, fecha, estado: e, stock_pct, productos, huecos, filas, motivos, umbral_pct, confianza, tiempo_s, miniatura }) =>
    ({ id, nombre, peso, tienda, jornada, fecha, estado: e, stock_pct, productos, huecos, filas, motivos, umbral_pct, confianza, tiempo_s, miniatura }));
  while (h.length && !guardarLocal(CLAVE_HIST, h)) h = h.slice(0, Math.floor(h.length * 0.7));   // si no cabe, recorta
}

/* ---------------- Utilidades ---------------- */
const fmtPct = (v) => (v === null || v === undefined || Number.isNaN(v)) ? "—" : `${Math.round(v)}%`;
const fmtPeso = (b) => b >= 1048576 ? `${(b / 1048576).toFixed(1)} MB` : `${(b / 1024).toFixed(1)} KB`;
const MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
function fmtFecha(iso, conHora = true) {
  if (!iso) return "—";
  const d = new Date(iso); if (Number.isNaN(+d)) return "—";
  let t = `${String(d.getDate()).padStart(2, "0")} ${MESES[d.getMonth()]} ${d.getFullYear()}`;
  if (conHora) {
    let h = d.getHours(); const m = String(d.getMinutes()).padStart(2, "0"); const pm = h >= 12; h = h % 12 || 12;
    t += `, ${h}:${m} ${pm ? "p. m." : "a. m."}`;
  }
  return t;
}
function hoyISO() { const d = new Date(); d.setMinutes(d.getMinutes() - d.getTimezoneOffset()); return d.toISOString().slice(0, 10); }
function escapar(s) { return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }
function icono(id) { return `<svg><use href="#${id}"/></svg>`; }
function chipEstado(e, largo = true) {
  const x = ESTADOS[e] || ESTADOS.REVISION_MANUAL;
  return `<span class="estado ${x.clase}">${icono(x.icono)}${largo ? x.largo : x.corto}</span>`;
}
let avisoTimer = null;
function avisar(texto, error = false) {
  const a = $("#aviso"); a.textContent = texto; a.classList.toggle("error", error); a.hidden = false;
  clearTimeout(avisoTimer); avisoTimer = setTimeout(() => (a.hidden = true), error ? 6000 : 3200);
}
function leerArchivo(f) {
  return new Promise((ok, mal) => { const r = new FileReader(); r.onload = () => ok(r.result); r.onerror = () => mal(r.error); r.readAsDataURL(f); });
}
function miniaturaDe(src, lado = 200) {
  return new Promise((ok) => {
    const img = new Image();
    img.onload = () => {
      const s = Math.min(1, lado / Math.max(img.width, img.height)); const c = document.createElement("canvas");
      c.width = Math.max(1, Math.round(img.width * s)); c.height = Math.max(1, Math.round(img.height * s));
      c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
      try { ok(c.toDataURL("image/jpeg", 0.72)); } catch { ok(""); }
    };
    img.onerror = () => ok(""); img.src = src;
  });
}
function descargar(nombre, contenido, tipo) {
  const url = contenido.startsWith("data:") ? contenido : URL.createObjectURL(new Blob([contenido], { type: tipo }));
  const a = document.createElement("a"); a.href = url; a.download = nombre; document.body.appendChild(a); a.click(); a.remove();
  if (!contenido.startsWith("data:")) setTimeout(() => URL.revokeObjectURL(url), 2000);
}
function abrirImagen(src) {
  if (!src) return avisar("La imagen anotada ya no está disponible (se guarda solo durante la sesión).", true);
  const w = window.open(); if (!w) return avisar("El navegador bloqueó la ventana emergente.", true);
  w.document.write(`<title>VisualShelf</title><body style="margin:0;background:#001E60;display:grid;place-items:center;min-height:100vh"><img src="${src}" style="max-width:100%;max-height:100vh">`);
}

/* ---------------- Navegación ---------------- */
function irA(vista) {
  if (!TITULOS[vista]) vista = "analizar";
  $$(".vista").forEach((v) => v.classList.toggle("activa", v.id === `vista-${vista}`));
  $$(".nav-item").forEach((b) => b.classList.toggle("activo", b.dataset.vista === vista));
  $("#miga-actual").textContent = TITULOS[vista];
  document.title = `VisualShelf · ${TITULOS[vista]}`;
  cerrarMenus(); cerrarLateral();
  if (vista === "resumen") pintarResumen();
  if (vista === "historial") pintarHistorial();
  if (vista === "alertas") pintarAlertas();
  if (vista === "config") pintarConfig();
  if (location.hash !== `#/${vista}`) history.replaceState(null, "", `#/${vista}`);
  window.scrollTo({ top: 0 });
}
function cerrarLateral() { $("#sidebar").classList.remove("abierta"); $("#velo").classList.remove("visible"); }
function cerrarMenus() { $("#menu-usuario").hidden = true; $("#menu-fila").hidden = true; estado.filaMenu = null; }

/* ---------------- Configuración del servidor ---------------- */
async function cargarConfig() {
  const pie = $("#estado-modelo");
  try {
    const r = await fetch("api/config"); const c = await r.json();
    estado.config = { ...estado.config, ...c };
    if (c.modelo_ok) { pie.textContent = `Modelo listo · ${c.modelo || "best.pt"}`; pie.className = "sidebar-pie ok"; }
    else { pie.textContent = c.error || "Modelo no cargado"; pie.className = "sidebar-pie error"; avisar(c.error || "El modelo no está cargado", true); }
  } catch {
    pie.textContent = "Sin conexión con el servidor"; pie.className = "sidebar-pie error";
  }
  const local = leerLocal(CLAVE_CONF, {});
  $("#umbral").value = local.umbral_pct ?? estado.config.umbral_pct;
  $("#confianza").value = local.confianza ?? estado.config.confianza;
  const tiendas = (local.tiendas && local.tiendas.length) ? local.tiendas : estado.config.tiendas;
  pintarTiendas(tiendas, local.tienda);
  $("#max-fotos").textContent = estado.config.max_fotos;
}
function pintarTiendas(tiendas, elegida) {
  const sel = $("#tienda"); sel.innerHTML = tiendas.map((t) => `<option>${escapar(t)}</option>`).join("");
  if (elegida && tiendas.includes(elegida)) sel.value = elegida;
}
function guardarPreferencias() {
  const tiendas = [...$("#tienda").options].map((o) => o.value);
  guardarLocal(CLAVE_CONF, { umbral_pct: +$("#umbral").value, confianza: +$("#confianza").value, tiendas, tienda: $("#tienda").value });
}

/* ---------------- Selección de archivos ---------------- */
const TIPOS = ["image/jpeg", "image/png", "image/webp", "image/bmp"];
function agregarArchivos(lista) {
  const max = estado.config.max_fotos;
  const nuevos = [...lista].filter((f) => TIPOS.includes(f.type) || /\.(jpe?g|png|webp|bmp)$/i.test(f.name));
  const ignorados = lista.length - nuevos.length;
  for (const f of nuevos) {
    if (estado.pendientes.length >= max) { avisar(`Máximo ${max} fotos por análisis.`, true); break; }
    if (!estado.pendientes.some((p) => p.name === f.name && p.size === f.size)) estado.pendientes.push(f);
  }
  if (ignorados > 0) avisar(`${ignorados} archivo(s) no son imágenes JPG/PNG y se ignoraron.`, true);
  pintarSeleccion();
}
function pintarSeleccion() {
  const cont = $("#seleccion"); const n = estado.pendientes.length;
  $("#analizar").disabled = n === 0 || estado.ocupado;
  if (!n) { cont.hidden = true; cont.innerHTML = ""; return; }
  cont.hidden = false;
  cont.innerHTML = estado.pendientes.map((f, i) => {
    if (!f._url) f._url = URL.createObjectURL(f);
    return `<div class="miniatura" title="${escapar(f.name)}"><img src="${f._url}" alt=""><button data-quitar="${i}" aria-label="Quitar">${icono("i-x")}</button></div>`;
  }).join("") + `<div class="seleccion-texto">${n} foto${n > 1 ? "s" : ""} lista${n > 1 ? "s" : ""} para analizar</div>`;
}

/* ---------------- Análisis ---------------- */
async function analizarTodo() {
  if (estado.ocupado || !estado.pendientes.length) return;
  const umbral = Math.min(90, Math.max(5, +$("#umbral").value || 30));
  const confianza = Math.min(0.95, Math.max(0.05, +$("#confianza").value || 0.35));
  $("#umbral").value = umbral; $("#confianza").value = confianza; guardarPreferencias();
  const tienda = $("#tienda").value; const jornada = $("#fecha").value;
  const archivos = estado.pendientes.slice(); estado.ocupado = true;
  const boton = $("#analizar"); boton.disabled = true;
  $("#progreso").hidden = false; $("#progreso-barra").style.width = "0%";
  estado.lote = []; estado.indice = 0; pintarLote(); pintarVisor();
  const t0 = performance.now();
  for (let i = 0; i < archivos.length; i++) {
    const f = archivos[i];
    $("span", boton).textContent = `Analizando ${i + 1} de ${archivos.length}…`;
    let res;
    try {
      const datos = await leerArchivo(f);
      const r = await fetch("api/analizar", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ nombre: f.name, imagen: datos, umbral, confianza }) });
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || `Error ${r.status}`);
      res = j;
    } catch (e) {
      res = { nombre: f.name, estado: "REVISION_MANUAL", stock_pct: null, productos: 0, huecos: 0, filas: 0,
              motivos: [`No se pudo analizar: ${e.message}`], umbral_pct: umbral, confianza, tiempo_s: 0, imagen_anotada: null };
    }
    const item = {
      ...res, id: `${Date.now()}-${i}-${Math.random().toString(36).slice(2, 7)}`, peso: f.size, tienda, jornada,
      fecha: res.fecha_captura || new Date(f.lastModified || Date.now()).toISOString(),
      original: f._url || URL.createObjectURL(f),
    };
    item.miniatura = await miniaturaDe(item.imagen_anotada || item.original);
    estado.lote.push(item);
    estado.historial.unshift(item);
    $("#progreso-barra").style.width = `${((i + 1) / archivos.length) * 100}%`;
    if (i === 0) estado.indice = 0;
    pintarLote(); pintarKPIs((performance.now() - t0) / 1000); pintarVisor();
  }
  guardarHistorial(); pintarContadorAlertas();
  estado.pendientes = []; estado.ocupado = false; pintarSeleccion();
  $("span", boton).textContent = "Analizar imágenes";
  setTimeout(() => ($("#progreso").hidden = true), 600);
  const n = estado.lote.filter((x) => x.estado === "ALERTA_REPONER").length;
  avisar(`Listo: ${estado.lote.length} foto(s) analizada(s)${n ? ` · ${n} para reabastecer` : ""}.`);
}

/* ---------------- Pintado: KPIs, visor, resultados, tabla ---------------- */
function promedioStock(lista) {
  const v = lista.map((x) => x.stock_pct).filter((x) => x !== null && x !== undefined);
  return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null;
}
function pintarKPIs(tiempoTotal) {
  const L = estado.lote;
  $("#k-fotos").textContent = L.length;
  $("#k-ocup").textContent = fmtPct(promedioStock(L));
  $("#k-reab").textContent = L.filter((x) => x.estado === "ALERTA_REPONER").length;
  if (tiempoTotal !== undefined) $("#k-tiempo").textContent = L.length ? `${tiempoTotal.toFixed(1)} s` : "—";
}
function pintarVisor() {
  const L = estado.lote; const n = L.length;
  if (estado.indice >= n) estado.indice = Math.max(0, n - 1);
  $("#paginas").textContent = `Imagen ${n ? estado.indice + 1 : 0} de ${n}`;
  $("#anterior").disabled = estado.indice <= 0; $("#siguiente").disabled = estado.indice >= n - 1;
  $("#csv").disabled = !n;
  const it = L[estado.indice];
  $("#vacio").hidden = !!it; $("#marco").hidden = !it;
  $$("#tabla-lote tr").forEach((tr) => tr.classList.toggle("sel", !!it && tr.dataset.id === it.id));
  if (!it) { pintarResultados(null); return; }
  const x = ESTADOS[it.estado] || ESTADOS.REVISION_MANUAL;
  const marco = $("#marco"); marco.className = `marco ${x.clase === "ok" ? "" : x.clase}`;
  marco.classList.toggle("zoom", +$("#zoom").value > 1);
  $("#insignia").innerHTML = `${icono(x.icono)}${x.corto} · ${fmtPct(it.stock_pct)}`;
  const src = (estado.verDetecciones && it.imagen_anotada) ? it.imagen_anotada : (it.original || it.imagen_anotada || it.miniatura);
  const img = $("#foto");
  img.onload = () => aplicarZoom();
  if (img.getAttribute("src") !== src) img.src = src; else aplicarZoom();
  pintarResultados(it);
}
function aplicarZoom() {
  const z = +$("#zoom").value; const img = $("#foto"); const marco = $("#marco");
  marco.classList.toggle("zoom", z > 1);
  if (z > 1) { const ancho = $("#lienzo").clientWidth; img.style.width = `${Math.round(ancho * z)}px`; }
  else img.style.width = "";
}
function pintarResultados(it) {
  const circ = 2 * Math.PI * 50; const arco = $("#m-valor");
  if (!it) {
    $("#m-pct").textContent = "—"; arco.style.strokeDashoffset = circ;
    const c = $("#chip-estado"); c.className = "chip"; c.textContent = "Sin analizar";
    ["#r-umbral", "#r-conf", "#r-prod", "#r-huecos", "#r-filas", "#r-nombre"].forEach((s) => ($(s).textContent = "—"));
    $("#r-peso").textContent = ""; $("#r-motivos").hidden = true; return;
  }
  const x = ESTADOS[it.estado] || ESTADOS.REVISION_MANUAL; const v = it.stock_pct;
  $("#m-pct").textContent = fmtPct(v);
  arco.style.stroke = `var(--${x.clase === "ok" ? "verde" : x.clase === "alerta" ? "rojo" : "naranjo"})`;
  arco.style.strokeDashoffset = v === null ? circ : circ * (1 - Math.max(0, Math.min(100, v)) / 100);
  const c = $("#chip-estado"); c.className = `chip ${x.clase}`; c.innerHTML = `${icono(x.icono)}${x.largo}`;
  $("#r-umbral").textContent = `${it.umbral_pct}%`;
  $("#r-conf").textContent = Number(it.confianza).toFixed(2);
  $("#r-prod").textContent = it.productos ?? "—"; $("#r-huecos").textContent = it.huecos ?? "—"; $("#r-filas").textContent = it.filas ?? "—";
  $("#r-nombre").textContent = it.nombre; $("#r-nombre").title = it.nombre; $("#r-peso").textContent = it.peso ? fmtPeso(it.peso) : "";
  const m = $("#r-motivos"); const motivos = it.motivos || [];
  if (motivos.length) {
    m.hidden = false; m.classList.toggle("info", it.estado === "OK");
    m.innerHTML = `<strong>${it.estado === "OK" ? "Notas" : "Motivos"}</strong><ul>${motivos.map((t) => `<li>${escapar(t)}</li>`).join("")}</ul>`;
  } else m.hidden = true;
}
function filaTabla(it, conTienda = false) {
  return `<tr data-id="${it.id}">
    <td><div class="foto-celda"><img src="${it.miniatura || ""}" alt=""><div><strong title="${escapar(it.nombre)}">${escapar(it.nombre)}</strong><span>${it.peso ? fmtPeso(it.peso) : ""}</span></div></div></td>
    ${conTienda ? `<td>${escapar(it.tienda || "—")}</td>` : ""}
    <td class="ocup">${fmtPct(it.stock_pct)}</td>
    <td>${chipEstado(it.estado)}</td>
    <td>${fmtFecha(it.fecha)}</td>
    <td><div class="acciones"><button class="icono-btn" data-accion="bajar" aria-label="Descargar imagen anotada">${icono("i-download")}</button><button class="icono-btn" data-accion="menu" aria-label="Más acciones">${icono("i-dots")}</button></div></td>
  </tr>`;
}
function pintarLote() {
  const tb = $("#tabla-lote");
  tb.innerHTML = estado.lote.length ? estado.lote.map((it) => filaTabla(it)).join("") : `<tr class="fila-vacia"><td colspan="5">Los resultados aparecerán aquí.</td></tr>`;
}

/* ---------------- CSV ---------------- */
function csvDe(lista) {
  const cab = ["foto", "tienda", "fecha_revision", "fecha_foto", "estado", "ocupacion_pct", "productos", "huecos", "filas", "umbral_pct", "confianza", "segundos", "motivos"];
  const q = (v) => { const s = String(v ?? ""); return /[",;\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
  const filas = lista.map((x) => [x.nombre, x.tienda, x.jornada, x.fecha, (ESTADOS[x.estado] || {}).largo || x.estado, x.stock_pct, x.productos, x.huecos, x.filas,
    x.umbral_pct, x.confianza, x.tiempo_s, (x.motivos || []).join(" | ")].map(q).join(","));
  return "﻿" + [cab.join(","), ...filas].join("\n");          // BOM: Excel muestra bien los acentos
}

/* ---------------- Vistas secundarias ---------------- */
function itemsFiltrados() {
  if (!$("#filtrar-hist").checked) return estado.historial;
  return estado.historial.filter((x) => x.tienda === $("#tienda").value && x.jornada === $("#fecha").value);
}
function pintarHistorial() {
  const L = itemsFiltrados(); const tb = $("#tabla-hist");
  tb.innerHTML = L.length ? L.map((it) => filaTabla(it, true)).join("") : `<tr class="fila-vacia"><td colspan="6">No hay análisis guardados${$("#filtrar-hist").checked ? " para esta tienda y fecha" : ""}.</td></tr>`;
}
function pintarAlertas() {
  const L = estado.historial.filter((x) => x.estado !== "OK");
  $("#lista-alertas").innerHTML = L.length ? L.map((it) => `
    <div class="alerta-tarj ${it.estado === "REVISION_MANUAL" ? "revision" : ""}" data-id="${it.id}">
      <img src="${it.miniatura || ""}" alt="">
      <div><strong title="${escapar(it.nombre)}">${escapar(it.nombre)}</strong>
        <p>${escapar(it.tienda || "")} · ${fmtFecha(it.fecha)} · ocupación ${fmtPct(it.stock_pct)}</p>
        ${chipEstado(it.estado)}
        ${(it.motivos || []).length ? `<p>${escapar(it.motivos[0])}</p>` : ""}
      </div>
    </div>`).join("") : `<div class="vacio-tarj">Sin alertas: todas las góndolas analizadas tienen stock adecuado.</div>`;
}
function kpiHTML(ico, clase, et, val) {
  return `<div class="kpi"><div class="kpi-ico ${clase}">${icono(ico)}</div><div><div class="kpi-et">${et}</div><div class="kpi-val">${val}</div></div></div>`;
}
function pintarResumen() {
  const H = estado.historial;
  $("#resumen-kpis").innerHTML = kpiHTML("i-camera", "azul", "Fotos analizadas", H.length) +
    kpiHTML("i-layers", "verde", "Ocupación media", fmtPct(promedioStock(H))) +
    kpiHTML("i-alert", "rojo", "Reabastecer", H.filter((x) => x.estado === "ALERTA_REPONER").length) +
    kpiHTML("i-info", "lila", "Revisión manual", H.filter((x) => x.estado === "REVISION_MANUAL").length);
  const grupos = {};
  for (const x of H) (grupos[x.tienda || "—"] ||= []).push(x);
  const filas = Object.entries(grupos).map(([t, L]) => `<tr data-tienda="${escapar(t)}"><td><strong>${escapar(t)}</strong></td><td>${L.length}</td><td class="ocup">${fmtPct(promedioStock(L))}</td>
    <td>${L.filter((x) => x.estado === "ALERTA_REPONER").length}</td><td>${L.filter((x) => x.estado === "REVISION_MANUAL").length}</td>
    <td>${fmtFecha(L.map((x) => x.jornada).filter(Boolean).sort().pop(), false)}</td></tr>`);
  $("#tabla-tiendas").innerHTML = filas.join("") || `<tr class="fila-vacia"><td colspan="6">Aún no hay análisis.</td></tr>`;
}
function pintarConfig() {
  const local = leerLocal(CLAVE_CONF, {});
  $("#c-umbral").value = $("#umbral").value; $("#c-conf").value = $("#confianza").value;
  $("#c-tiendas").value = [...$("#tienda").options].map((o) => o.value).join("\n");
  const c = estado.config;
  $("#ficha-modelo").innerHTML = [
    ["Estado", c.modelo_ok ? "Cargado" : (c.error || "No cargado")], ["Archivo", c.modelo || "—"],
    ["Umbral calibrado", `${c.umbral_pct}%`], ["Confianza calibrada", c.confianza], ["Zona de góndola", c.zona === "detecciones" ? "Desde las detecciones" : (c.zona || "Sin filtro")],
    ["Bordes de fila", c.bordes === false || c.bordes === null ? "No se cuentan (recomendado)" : c.bordes], ["Fotos por análisis", c.max_fotos],
    ["Datos guardados", `${estado.historial.length} análisis en este navegador`],
  ].map(([k, v]) => `<dt>${k}</dt><dd>${escapar(v)}</dd>`).join("");
  void local;
}
function pintarContadorAlertas() {
  const n = estado.historial.filter((x) => x.estado === "ALERTA_REPONER").length;
  const c = $("#nav-alertas"); c.hidden = !n; c.textContent = n; $("#punto").hidden = !n;
}

/* ---------------- Acciones sobre filas ---------------- */
function buscar(id) { return estado.lote.find((x) => x.id === id) || estado.historial.find((x) => x.id === id); }
function verEnVisor(id) {
  let i = estado.lote.findIndex((x) => x.id === id);
  if (i < 0) { const it = buscar(id); if (!it) return; estado.lote = [it]; i = 0; pintarLote(); pintarKPIs(it.tiempo_s || 0); }
  estado.indice = i; irA("analizar"); pintarVisor();
}
function eliminar(id) {
  estado.lote = estado.lote.filter((x) => x.id !== id);
  estado.historial = estado.historial.filter((x) => x.id !== id);
  guardarHistorial(); pintarLote(); pintarKPIs(); pintarVisor(); pintarHistorial(); pintarAlertas(); pintarContadorAlertas();
  avisar("Análisis eliminado.");
}
function manejarTabla(e) {
  const tr = e.target.closest("tr[data-id]"); if (!tr) return;
  const id = tr.dataset.id; const btn = e.target.closest("button[data-accion]");
  if (!btn) return verEnVisor(id);
  e.stopPropagation();
  const it = buscar(id);
  if (btn.dataset.accion === "bajar") {
    const src = it?.imagen_anotada || it?.miniatura;
    if (!src) return avisar("No hay imagen para descargar.", true);
    if (!it.imagen_anotada) avisar("Solo queda la miniatura: la imagen completa se guarda durante la sesión.");
    descargar(`${(it.nombre || "foto").replace(/\.[^.]+$/, "")}_analizada.jpg`, src);
  } else if (btn.dataset.accion === "menu") {
    const m = $("#menu-fila"); const r = btn.getBoundingClientRect();
    estado.filaMenu = id; m.hidden = false;
    m.style.top = `${Math.min(window.innerHeight - m.offsetHeight - 8, r.bottom + 6)}px`;
    m.style.left = `${Math.max(8, r.right - m.offsetWidth)}px`;
  }
}

/* ---------------- Eventos ---------------- */
function iniciar() {
  estado.historial = leerLocal(CLAVE_HIST, []);
  pintarContadorAlertas();
  const f = $("#fecha"); f.value = hoyISO();
  const pintarFecha = () => ($("#fecha-texto").textContent = fmtFecha(`${f.value}T12:00:00`, false));
  pintarFecha(); f.addEventListener("change", () => { pintarFecha(); pintarHistorial(); });
  $("#tienda").addEventListener("change", () => { guardarPreferencias(); pintarHistorial(); });

  $$(".nav-item, #menu-usuario [data-vista]").forEach((b) => b.addEventListener("click", () => irA(b.dataset.vista)));
  $("#campana").addEventListener("click", () => irA("alertas"));
  $("#menu-btn").addEventListener("click", () => { $("#sidebar").classList.add("abierta"); $("#velo").classList.add("visible"); });
  $("#velo").addEventListener("click", cerrarLateral);
  $("#avatar").addEventListener("click", (e) => { e.stopPropagation(); const m = $("#menu-usuario"); m.hidden = !m.hidden; });
  document.addEventListener("click", (e) => { if (!e.target.closest(".menu-flotante, #avatar")) cerrarMenus(); });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") cerrarMenus();
    if (!$("#vista-analizar").classList.contains("activa") || e.target.matches("input, select, textarea")) return;
    if (e.key === "ArrowLeft") $("#anterior").click();
    if (e.key === "ArrowRight") $("#siguiente").click();
  });
  $("#borrar-historial").addEventListener("click", () => {
    if (!estado.historial.length) return avisar("El historial ya está vacío.");
    estado.historial = []; guardarHistorial(); pintarContadorAlertas(); pintarHistorial(); pintarAlertas(); cerrarMenus(); avisar("Historial borrado.");
  });

  // Carga de archivos
  const zona = $("#zona-drop"); const input = $("#archivos");
  input.addEventListener("change", () => { agregarArchivos(input.files); input.value = ""; });
  ["dragenter", "dragover"].forEach((t) => zona.addEventListener(t, (e) => { e.preventDefault(); zona.classList.add("encima"); }));
  ["dragleave", "drop"].forEach((t) => zona.addEventListener(t, (e) => { e.preventDefault(); zona.classList.remove("encima"); }));
  zona.addEventListener("drop", (e) => agregarArchivos(e.dataTransfer.files));
  document.addEventListener("dragover", (e) => e.preventDefault());
  document.addEventListener("drop", (e) => { e.preventDefault(); if (!e.target.closest("#zona-drop") && $("#vista-analizar").classList.contains("activa")) agregarArchivos(e.dataTransfer.files); });
  $("#seleccion").addEventListener("click", (e) => {
    const b = e.target.closest("[data-quitar]"); if (!b) return;
    e.preventDefault(); estado.pendientes.splice(+b.dataset.quitar, 1); pintarSeleccion();
  });
  $("#analizar").addEventListener("click", analizarTodo);
  ["#umbral", "#confianza"].forEach((s) => $(s).addEventListener("change", guardarPreferencias));

  // Visor
  $("#anterior").addEventListener("click", () => { if (estado.indice > 0) { estado.indice--; pintarVisor(); } });
  $("#siguiente").addEventListener("click", () => { if (estado.indice < estado.lote.length - 1) { estado.indice++; pintarVisor(); } });
  const modo = (det) => {
    estado.verDetecciones = det; $("#mostrar-det").checked = det;
    $("#ver-det").classList.toggle("activo", det); $("#ver-orig").classList.toggle("activo", !det); pintarVisor();
  };
  $("#ver-det").addEventListener("click", () => modo(true));
  $("#ver-orig").addEventListener("click", () => modo(false));
  $("#mostrar-det").addEventListener("change", (e) => modo(e.target.checked));
  $("#zoom").addEventListener("change", aplicarZoom);
  window.addEventListener("resize", aplicarZoom);
  $("#abrir").addEventListener("click", () => { const it = estado.lote[estado.indice]; if (it) abrirImagen(estado.verDetecciones ? it.imagen_anotada : it.original); });
  $("#csv").addEventListener("click", () => descargar(`visualshelf_${$("#fecha").value}.csv`, csvDe(estado.lote), "text/csv;charset=utf-8"));
  $("#csv-hist").addEventListener("click", () => {
    const L = itemsFiltrados(); if (!L.length) return avisar("No hay datos para descargar.", true);
    descargar("visualshelf_historial.csv", csvDe(L), "text/csv;charset=utf-8");
  });
  $("#filtrar-hist").addEventListener("change", pintarHistorial);

  // Tablas y tarjetas
  $("#tabla-lote").addEventListener("click", manejarTabla);
  $("#tabla-hist").addEventListener("click", manejarTabla);
  $("#lista-alertas").addEventListener("click", (e) => { const t = e.target.closest("[data-id]"); if (t) verEnVisor(t.dataset.id); });
  $("#tabla-tiendas").addEventListener("click", (e) => {
    const t = e.target.closest("[data-tienda]"); if (!t) return;
    const sel = $("#tienda"); if ([...sel.options].some((o) => o.value === t.dataset.tienda)) sel.value = t.dataset.tienda;
    $("#filtrar-hist").checked = false; irA("historial");
  });
  $("#menu-fila").addEventListener("click", (e) => {
    const b = e.target.closest("[data-accion]"); const id = estado.filaMenu; cerrarMenus(); if (!b || !id) return;
    const it = buscar(id);
    if (b.dataset.accion === "ver") verEnVisor(id);
    if (b.dataset.accion === "abrir") abrirImagen(it?.imagen_anotada);
    if (b.dataset.accion === "eliminar") eliminar(id);
  });

  // Configuración
  $("#c-guardar").addEventListener("click", () => {
    $("#umbral").value = Math.min(90, Math.max(5, +$("#c-umbral").value || 30));
    $("#confianza").value = Math.min(0.95, Math.max(0.05, +$("#c-conf").value || 0.35));
    const tiendas = $("#c-tiendas").value.split("\n").map((t) => t.trim()).filter(Boolean);
    pintarTiendas(tiendas.length ? tiendas : estado.config.tiendas, $("#tienda").value);
    guardarPreferencias(); pintarConfig(); avisar("Configuración guardada.");
  });
  $("#c-restaurar").addEventListener("click", () => {
    $("#umbral").value = estado.config.umbral_pct; $("#confianza").value = estado.config.confianza;
    guardarPreferencias(); pintarConfig(); avisar("Se restauraron los valores calibrados del modelo.");
  });

  cargarConfig();
  irA(location.hash.replace(/^#\/?/, "") || "analizar");
  pintarVisor();
}
document.addEventListener("DOMContentLoaded", iniciar);
