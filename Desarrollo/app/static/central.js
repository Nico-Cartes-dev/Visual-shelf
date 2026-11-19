"use strict";
let clienteAuth;
let aplicacionIniciada = false;
let recuperando = false;
let paginaHistorial = 0;
let paginaAlertas = 0;
let resumenCentral = [];

async function api(ruta, opciones = {}) {
  const { data: { session }, error } = await clienteAuth.auth.getSession();
  if (error || !session) throw new Error("Inicia sesion para continuar.");
  const r = await fetch(ruta, { ...opciones, headers: { "Content-Type": "application/json",
    ...opciones.headers, Authorization: `Bearer ${session.access_token}` } });
  if (!r.ok) {
    const dato = await r.json().catch(() => ({}));
    if (r.status === 401) { await clienteAuth.auth.signOut({ scope: "local" }); }
    const error = new Error(dato.error || `Error ${r.status}`);
    error.status = r.status;
    throw error;
  }
  return r;
}

async function cargarHistorialCentral(reiniciar = true) {
  if (reiniciar) paginaHistorial = 0;
  const q = new URLSearchParams({ pagina: paginaHistorial });
  if (document.querySelector("#filtrar-hist").checked) {
    q.set("tienda", document.querySelector("#tienda").value);
    q.set("jornada", document.querySelector("#fecha").value);
  }
  const dato = await (await api(`api/analisis?${q}`)).json();
  estado.historial = reiniciar ? dato.items : [...estado.historial, ...dato.items];
  document.querySelector("#hist-mas").hidden = !dato.mas;
  paginaHistorial++;
  pintarHistorial();
}

async function cargarAlertasCentral(reiniciar = true) {
  if (reiniciar) paginaAlertas = 0;
  const dato = await (await api(`api/analisis?alertas=1&pagina=${paginaAlertas}`)).json();
  estado.alertas = reiniciar ? dato.items : [...estado.alertas, ...dato.items];
  document.querySelector("#alertas-mas").hidden = !dato.mas;
  paginaAlertas++;
  pintarAlertas();
}

async function actualizarCentral() {
  resumenCentral = await (await api("api/resumen")).json();
  await cargarHistorialCentral();
  await cargarAlertasCentral();
  pintarResumen(); pintarContadorAlertas();
}

async function cargarImagenes(it) {
  if (it.origen === "importado") return;
  for (const [tipo, campo] of [["original", "original"], ["anotada", "imagen_anotada"]]) {
    if (!it[campo]) {
      const r = await api(`api/analisis/${encodeURIComponent(it.id)}/${tipo}`);
      it[campo] = URL.createObjectURL(await r.blob());
    }
  }
}

function lanzar(operacion) { operacion().catch(e => avisar(e.message, true)); }

async function importarAntiguo() {
  const tienda = document.querySelector("#tienda");
  const originales = leerLocal(CLAVE_HIST, []);
  const items = originales.filter(x => x.tienda === tienda.selectedOptions[0]?.textContent);
  if (!items.length) return avisar("No hay historial local de esta tienda para importar.");
  if (!confirm(`Importar ${items.length} analisis antiguos a ${tienda.selectedOptions[0].textContent}? Los registros quedaran compartidos con esta tienda. Las fotos completas no se recuperan.`)) return;
  await api("api/importar", { method: "POST", body: JSON.stringify({ tienda_id: tienda.value, items }) });
  await actualizarCentral();
  avisar("Importacion completada. El historial local se conserva; repetir no duplica registros.");
}

async function activarSesion(session) {
  const panel = document.querySelector("#acceso");
  if (!session) {
    if (aplicacionIniciada) { location.reload(); return; }
    panel.hidden = false;
    document.querySelector(".app").hidden = true;
    return;
  }
  if (recuperando) {
    panel.hidden = false;
    document.querySelector("#acceso-titulo").textContent = "Crea tu contraseña";
    document.querySelector("#acceso-descripcion").textContent = "Define una contraseña para acceder a tu espacio de trabajo.";
    document.querySelector("#login").hidden = true;
    document.querySelector("#nueva-clave").hidden = false;
    return;
  }
  if (!aplicacionIniciada) {
    await iniciar();
    aplicacionIniciada = true;
    document.querySelector("#usuario-email").textContent = session.user.email;
    document.querySelector("#avatar").textContent = session.user.email.slice(0,2).toUpperCase();
  }
  await actualizarCentral();
  panel.hidden = true;
  document.querySelector(".app").hidden = false;
}

document.addEventListener("DOMContentLoaded", async () => {
  const mensaje = document.querySelector("#acceso-mensaje");
  document.querySelector("#ver-password").addEventListener("click", e => {
    const campo = document.querySelector("#password");
    const visible = campo.type === "password";
    campo.type = visible ? "text" : "password";
    e.currentTarget.setAttribute("aria-pressed", String(visible));
    e.currentTarget.setAttribute("aria-label", visible ? "Ocultar contraseña" : "Mostrar contraseña");
  });
  for (const id of ["#login", "#nueva-clave"])
    document.querySelector(id).addEventListener("submit", e => e.preventDefault());
  recuperando = ["recovery", "invite"].includes(new URLSearchParams(location.hash.slice(1)).get("type"));
  try {
    const r = await fetch("api/auth-config");
    const conf = await r.json();
    if (!r.ok) throw new Error(conf.error);
    if (!window.supabase) throw new Error("No se pudo cargar el acceso. Revisa tu conexion y recarga.");
    clienteAuth = window.supabase.createClient(conf.url, conf.key);
    document.querySelector("#login").addEventListener("submit", async e => {
      e.preventDefault(); mensaje.textContent = "Ingresando…";
      const boton = document.querySelector("#ingresar");
      boton.disabled = true;
      boton.setAttribute("aria-busy", "true");
      boton.querySelector("span").textContent = "Ingresando…";
      try {
        const { data, error } = await clienteAuth.auth.signInWithPassword({ email: document.querySelector("#email").value,
          password: document.querySelector("#password").value });
        if (error) throw new Error("Correo o contraseña incorrectos, o cuenta no habilitada.");
        document.querySelector("#password").value = "";
        await activarSesion(data.session);
        mensaje.textContent = "";
      } catch (error) { mensaje.textContent = error.message; }
      finally {
        boton.disabled = false;
        boton.removeAttribute("aria-busy");
        boton.querySelector("span").textContent = "Ingresar a VisualShelf";
      }
    });
    document.querySelector("#recuperar").addEventListener("click", async () => {
      const email = document.querySelector("#email").value;
      if (!email) { mensaje.textContent = "Ingresa primero tu correo."; return; }
      const { error } = await clienteAuth.auth.resetPasswordForEmail(email, { redirectTo: location.origin + "/" });
      mensaje.textContent = error ? "No se pudo solicitar la recuperacion. Intenta mas tarde." : "Si la cuenta existe, recibiras un enlace para recuperar el acceso.";
    });
    document.querySelector("#nueva-clave").addEventListener("submit", async e => {
      e.preventDefault();
      const { error } = await clienteAuth.auth.updateUser({ password: document.querySelector("#clave-nueva").value });
      if (error) { mensaje.textContent = "No se pudo actualizar la contraseña."; return; }
      recuperando = false; location.replace(location.pathname);
    });
    document.querySelector("#salir").addEventListener("click", () => lanzar(async () => {
      const { error } = await clienteAuth.auth.signOut();
      if (error) throw error;
      location.reload();
    }));
    clienteAuth.auth.onAuthStateChange((evento, sesion) => {
      if (evento === "PASSWORD_RECOVERY") recuperando = true;
      if (evento === "SIGNED_OUT" || evento === "PASSWORD_RECOVERY")
        setTimeout(() => activarSesion(sesion).catch(e => { mensaje.textContent = e.message; }), 0);
    });
    // shortcut: recuperacion por enlace en este navegador, configurar redirect URL al publicar.
    const { data, error } = await clienteAuth.auth.getSession();
    if (error) throw error;
    await activarSesion(data.session);
  } catch (error) { mensaje.textContent = error.message; }
});
