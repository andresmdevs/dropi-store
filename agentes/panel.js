"use strict";

const $ = (id) => document.getElementById(id);
let csrf = "";
let cargando = false;
const safe = (value) => String(value ?? "").replace(/[&<>"']/g,
  (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
const fecha = (iso) => {
  if (!iso) return "—";
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString();
};

function mostrarLogin(error) {
  $("app").classList.add("hidden");
  $("login").classList.remove("hidden");
  if (error === "auth") $("login-message").textContent = "No se pudo autorizar esta cuenta. Verifica el acceso permitido.";
  fetch("/auth/status", { cache: "no-store" }).then((response) => response.json()).then((data) => {
    if (!data.configurado) {
      $("login-message").textContent = "Panel desplegado. Falta configurar la GitHub OAuth App en Render.";
      $("login-link").classList.add("hidden");
    }
  }).catch(() => {});
}

function render(data) {
  $("app").classList.remove("hidden");
  $("login").classList.add("hidden");
  csrf = data.csrf;
  const local = data.local;
  const conectado = local && Date.now() - new Date(local.actualizado).getTime() < 90000;
  $("connection").innerHTML = `<span class="badge ${conectado ? "online" : "offline"}">${conectado ? "Mac conectado" : "Mac desconectado"}</span> · ${safe(data.usuario)}`;
  $("service").textContent = conectado ? local.servicio : "desconectado";
  $("service").className = `badge ${conectado ? (local.servicio === "corriendo" ? "online" : "warn") : "offline"}`;
  $("ollama").textContent = `Ollama: ${conectado && local.ollama ? "disponible" : "no disponible"}`;
  $("agents").innerHTML = conectado && local.agentes.length ? local.agentes.map((agent) =>
    `<article class="card"><div class="row"><strong>${safe(agent.agente)}</strong><span class="badge">${safe(agent.estado)}</span></div>
    <div class="muted">${safe(agent.modelo || "sin modelo")}</div><div class="task">${safe(agent.tarea || "—")}</div>
    <small>Latido hace ${Math.round(agent.edad_s)} s</small></article>`).join("")
    : '<div class="card empty">Sin reporte reciente de agentes.</div>';
  $("models").innerHTML = conectado && local.modelos.length ? local.modelos.map((model) =>
    `<article class="card">${safe(model)}</article>`).join("")
    : '<div class="card empty">No hay modelos cargados o el Mac está desconectado.</div>';
  const counts = data.interacciones.conteos || {};
  $("queue").innerHTML = ["pendiente", "revision", "respondida", "atendida"].map((state) =>
    `<article class="card"><div class="muted">${safe(state)}</div><div class="count">${Number(counts[state] || 0)}</div></article>`).join("");
  $("reviews").innerHTML = (data.interacciones.revision || []).length
    ? data.interacciones.revision.map((item) => `<article class="card interaction">
      <div class="row"><strong>${safe(item.red)} · ${safe(item.tipo)}</strong><small>${safe(fecha(item.recibido))}</small></div>
      <p>${safe(item.texto)}</p><p class="muted">${safe(item.detalle)}</p>
      <button data-attend="${Number(item.id)}">Marcar atendida</button></article>`).join("")
    : '<div class="card empty">No hay casos pendientes de revisión.</div>';
  const comando = data.comandos?.[0];
  $("command-status").textContent = comando
    ? `Última acción: ${comando.accion} · ${comando.estado}${comando.detalle ? ` · ${comando.detalle}` : ""}`
    : "";
  $("updated").textContent = `Actualizado ${fecha(data.local?.actualizado)}`;
}

async function cargar() {
  if (cargando) return;
  cargando = true;
  try {
    const response = await fetch("/api/panel", { credentials: "same-origin", cache: "no-store" });
    if (response.status === 401) return mostrarLogin(new URLSearchParams(location.search).get("error"));
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    render(await response.json());
  } catch (error) {
    $("connection").textContent = `No se pudo actualizar: ${error.message}`;
  } finally {
    cargando = false;
  }
}

async function post(path, payload) {
  const response = await fetch(path, {
    method: "POST", credentials: "same-origin", cache: "no-store",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

$("refresh").addEventListener("click", cargar);
$("start").addEventListener("click", () => enviarAccion("iniciar"));
$("stop").addEventListener("click", () => enviarAccion("detener"));
$("logout").addEventListener("click", async () => {
  try { await post("/api/panel/logout", {}); } finally { location.reload(); }
});
$("reviews").addEventListener("click", async (event) => {
  const button = event.target.closest("[data-attend]");
  if (!button) return;
  button.disabled = true;
  try { await post("/api/panel/attend", { id: Number(button.dataset.attend) }); await cargar(); }
  catch (error) { button.disabled = false; alert(`No se pudo actualizar: ${error.message}`); }
});

async function enviarAccion(accion) {
  const button = accion === "iniciar" ? $("start") : $("stop");
  button.disabled = true;
  try {
    const result = await post("/api/panel/command", { accion });
    $("command-status").textContent = `Acción ${accion} en cola (#${result.id}).`;
    setTimeout(cargar, 1500);
  } catch (error) {
    $("command-status").textContent = `No se pudo enviar la acción: ${error.message}`;
  } finally { button.disabled = false; }
}

if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
cargar();
setInterval(cargar, 15000);
