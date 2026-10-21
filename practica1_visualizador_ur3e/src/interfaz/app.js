"use strict";

const POLL_MS = 300;
const MAX_LOG_LINES = 500;
const HOST_PATTERN = /^[A-Za-z0-9.\-]{1,253}$/;
const JOINT_RANGE = 2 * Math.PI;  // UR3e joints move within ±2π rad
const STATUS = {
  connecting: ["conectando", "warn"],
  connected: ["conectado", "ok"],
  disconnected: ["desconectado · reintentando", "err"],
  unreachable: ["inalcanzable · reintentando", "err"],
  error: ["datos no válidos · detenido", "err"],
};
const INTERFACE = {
  primaria: ["primaria · 10 Hz", ""],
  tiempo_real: ["tiempo real · 500 Hz", "rt"],
};
const ICON_TRASH = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/></svg>`;
const ICON_CROSS = `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg>`;

const $ = id => document.getElementById(id);
const ui = {
  iface: "primaria",
  nextLog: 0,
  hostsKey: "",
  pointsKey: "",
  pointCount: 0,
  progressState: "idle",
  modal: null,          // kind of the open modal
  decisionId: null,     // failure already shown to the operator
  teach: { points: [], running: false, saved_as: null },
  hosts: [],
};

/* ======================= SERVER ======================= */
async function api(path, body) {
  const options = body === undefined
    ? {}
    : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const response = await fetch(path, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `Error ${response.status}`);
  return data;
}

async function action(fn, button) {
  if (button) button.disabled = true;
  try {
    return await fn();
  } catch (error) {
    toast("err", error.message);
  } finally {
    if (button) button.disabled = false;
  }
}

async function poll() {
  try {
    const state = await api(`/api/estado?desde=${ui.nextLog}`);
    $("offline").classList.remove("show");
    if (state.next_log < ui.nextLog) ui.nextLog = 0;  // the server was restarted
    else applyState(state);
  } catch {
    $("offline").classList.add("show");
  }
  setTimeout(poll, POLL_MS);
}

function applyState(state) {
  renderVisualizer(state.visualizer);
  renderHosts(state.hosts);
  renderTeach(state.teach);
  appendLogs(state.logs);
  ui.nextLog = state.next_log;
}

/* ======================= NAVIGATION ======================= */
function showPage(name) {
  document.querySelectorAll(".page").forEach(page => page.classList.toggle("active", page.id === "page-" + name));
  document.querySelectorAll("#nav button").forEach(button => button.classList.toggle("active", button.dataset.page === name));
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function setInterface(iface) {
  ui.iface = iface;
  document.querySelectorAll("#ifaceSeg button").forEach(button => button.classList.toggle("active", button.dataset.iface === iface));
}

/* ======================= LOGS & TOASTS ======================= */
function appendLogs(entries) {
  for (const entry of entries) {
    const box = $("log-" + entry.channel);
    const stick = box.scrollTop + box.clientHeight >= box.scrollHeight - 20;
    const line = document.createElement("div");
    line.className = "log-line " + entry.level;
    line.innerHTML = `<span class="t"></span><span class="lv ${entry.level}"></span><span class="m"></span>`;
    line.querySelector(".t").textContent = entry.time;
    line.querySelector(".lv").textContent = entry.level;
    line.querySelector(".m").textContent = entry.message;
    box.appendChild(line);
    while (box.childElementCount > MAX_LOG_LINES) box.firstElementChild.remove();
    if (stick) box.scrollTop = box.scrollHeight;
  }
}

function toast(kind, message) {
  const element = document.createElement("div");
  element.className = "toast " + kind;
  element.innerHTML = `<span class="dot ${kind}"></span><span></span>`;
  element.lastChild.textContent = message;
  $("toasts").appendChild(element);
  setTimeout(() => {
    element.style.transition = "opacity .3s";
    element.style.opacity = 0;
    setTimeout(() => element.remove(), 300);
  }, 3500);
}

/* ======================= MODALS ======================= */
function openModal(kind, html) {
  ui.modal = kind;
  $("modalBody").innerHTML = html;
  $("modal").classList.add("show");
}

function closeModal() {
  ui.modal = null;
  $("modal").classList.remove("show");
}

function closableModal() {
  return ui.modal !== null && ui.modal !== "decision";  // the operator must answer a failure
}

/* ======================= VISUALIZER ======================= */
function renderVisualizer(open) {
  $("vizPill").innerHTML = `<span class="dot ${open ? "ok" : ""}"></span>Visualizador ${open ? "abierto" : "cerrado"}`;
  $("vizBanner").classList.toggle("open", open);
  $("vizTitle").textContent = open ? "Visualizador 3D abierto" : "Visualizador 3D cerrado";
  $("vizText").textContent = open
    ? "La ventana UR3eRG2 muestra un robot por cada host, separados 0,8 m."
    : "El visualizador UR3eRG2 se abre en una ventana aparte, junto al navegador.";
  $("vizBtnTop").disabled = open;
  $("vizBtnBanner").disabled = open;
}

function openVisualizer(button) {
  return action(async () => {
    await api("/api/visualizador/abrir", {});
    toast("ok", "Visualizador abierto en una ventana aparte");
  }, button);
}

/* ======================= MONITORING ======================= */
function renderHosts(hosts) {
  ui.hosts = hosts;
  const key = JSON.stringify(hosts.map(h => [h.host, h.interface, h.status, h.body]));
  if (key !== ui.hostsKey) {
    ui.hostsKey = key;
    buildHostList(hosts);
    buildRobotCards(hosts);
  }
  for (const host of hosts) {
    const card = document.querySelector(`.robot[data-host="${CSS.escape(host.host)}"]`);
    if (card) paintJoints(card, host.joints);
  }
}

function buildHostList(hosts) {
  $("hostCount").textContent = hosts.length;
  const list = $("hostList");
  list.innerHTML = hosts.length ? "" : `<div class="empty"><b>Ningún robot</b>Añade una IP para empezar a monitorizar.</div>`;
  for (const host of hosts) {
    const [label, dot] = STATUS[host.status] || [host.status, ""];
    const [ifaceLabel, ifaceClass] = INTERFACE[host.interface];
    const row = document.createElement("div");
    row.className = "host-row";
    row.innerHTML = `<span class="dot ${dot}"></span>
      <div class="grow"><div class="ip"></div><div class="state"></div></div>
      <span class="badge ${ifaceClass}"></span>
      <button class="icon-btn" title="Eliminar robot">${ICON_TRASH}</button>`;
    row.querySelector(".ip").textContent = host.host;
    row.querySelector(".state").textContent = label;
    row.querySelector(".badge").textContent = ifaceLabel.split(" · ")[0];
    const button = row.querySelector("button");
    button.onclick = () => action(async () => {
      await api("/api/hosts/eliminar", { host: host.host });
      toast("ok", `Robot ${host.host} eliminado`);
    }, button);
    list.appendChild(row);
  }
}

function buildRobotCards(hosts) {
  $("robotCount").textContent = `${hosts.length} robot${hosts.length === 1 ? "" : "s"}`;
  const robots = $("robots");
  robots.innerHTML = hosts.length
    ? ""
    : `<div class="empty" style="grid-column:1/-1"><b>Sin robots</b>Los robots que añadas aparecerán aquí con su posición articular en directo.</div>`;
  for (const host of hosts) {
    const [, dot] = STATUS[host.status] || ["", ""];
    const [ifaceLabel, ifaceClass] = INTERFACE[host.interface];
    const card = document.createElement("div");
    card.className = "robot";
    card.dataset.host = host.host;
    card.innerHTML = `<div class="robot-h"><span class="dot ${dot}"></span><span class="ip"></span>
      <span class="badge ${ifaceClass}"></span><span class="body"></span></div>
      ${[1, 2, 3, 4, 5, 6].map(n => `<div class="joint"><span class="name">J${n}</span><div class="bar"><i></i></div><span class="val">—</span></div>`).join("")}`;
    card.querySelector(".ip").textContent = host.host;
    card.querySelector(".badge").textContent = ifaceLabel;
    card.querySelector(".body").textContent = host.body === null ? "sin visualizador" : `cuerpo ${host.body}`;
    robots.appendChild(card);
  }
}

function paintJoints(card, joints) {
  card.querySelectorAll(".joint").forEach((row, index) => {
    const bar = row.querySelector("i");
    if (!joints) {
      bar.style.width = "0";
      row.querySelector(".val").textContent = "—";
      return;
    }
    const fraction = Math.max(-1, Math.min(1, joints[index] / JOINT_RANGE));
    bar.style.left = (fraction < 0 ? 50 + fraction * 50 : 50) + "%";
    bar.style.width = Math.abs(fraction) * 50 + "%";
    row.querySelector(".val").textContent = joints[index].toFixed(4) + " rad";
  });
}

function addHost(host, iface, button) {
  return action(async () => {
    await api("/api/hosts/anadir", { host, interface: iface });
    toast("ok", `Robot ${host} añadido`);
    return true;
  }, button);
}

/* ======================= TEACH ======================= */
function requireHost(input, message) {
  const host = input.value.trim();
  const valid = HOST_PATTERN.test(host);
  input.classList.toggle("invalid", !valid);
  if (!valid) toast("err", message);
  return valid ? host : null;
}

const grabHost = () => requireHost($("grabHost"), "El host de captura es obligatorio");

function executionHost() {
  const write = $("writeHost").value.trim();
  if (!write) return grabHost();
  return requireHost($("writeHost"), "El host de ejecución no es válido");
}

function renderTeach(teach) {
  ui.teach = teach;
  const key = JSON.stringify([teach.points, teach.progress, teach.running]);
  if (key !== ui.pointsKey) {
    ui.pointsKey = key;
    renderPoints(teach);
  }
  for (const id of ["grabBtn", "saveBtn", "loadBtn", "runBtn"]) $(id).disabled = teach.running;
  renderProgress(teach.progress);
  renderDecision(teach.decision);
}

function renderPoints(teach) {
  const { points, progress, running } = teach;
  const added = points.length > ui.pointCount;
  ui.pointCount = points.length;
  const current = progress.state === "moving" ? progress.point - 1 : -1;
  const failed = progress.state === "stopped" ? progress.point - 1 : -1;
  const body = $("pointsBody");
  body.innerHTML = "";
  points.forEach((point, index) => {
    const row = document.createElement("tr");
    if (added && index === points.length - 1) row.className = "new";
    if (running && index < Math.max(current, failed)) row.className = "done";
    if (index === current) row.className = "current";
    if (index === failed) row.className = "failed";
    row.innerHTML = `<td><span class="num">${index + 1}</span></td>
      ${point.map(value => `<td>${value.toFixed(4)}</td>`).join("")}
      <td><button class="icon-btn" title="Eliminar punto" ${running ? "disabled" : ""}>${ICON_CROSS}</button></td>`;
    const button = row.querySelector("button");
    button.onclick = () => action(() => api("/api/ensenar/borrar", { index }), button);
    body.appendChild(row);
  });
  $("pointsEmpty").style.display = points.length ? "none" : "block";
  $("pointCount").textContent = `${points.length} punto${points.length === 1 ? "" : "s"} · rad`;
}

function renderProgress(progress) {
  const total = progress.total || 0;
  let label = "Sin ejecutar", done = 0, kind = "";
  switch (progress.state) {
    case "moving": label = `Punto ${progress.point} de ${total} · moviendo`; done = progress.point - 1; break;
    case "stopped": label = `Detenida en el punto ${progress.point} de ${total}`; done = progress.point - 1; kind = "err"; break;
    case "completed": label = "Secuencia completada"; done = total; kind = "ok"; break;
    case "cancelled": label = "Secuencia cancelada"; done = progress.point - 1; kind = "err"; break;
    case "error": label = "Error en la ejecución, revisa el registro"; kind = "err"; break;
  }
  const percent = total ? Math.round(Math.max(0, done) / total * 100) : 0;
  $("progLabel").textContent = label;
  $("progPct").textContent = percent + " %";
  $("progFill").style.width = percent + "%";
  $("progFill").className = "progress-fill " + kind;

  if (progress.state !== ui.progressState) {
    if (progress.state === "completed") toast("ok", "Secuencia completada");
    if (progress.state === "cancelled") toast("warn", "Secuencia cancelada");
    if (progress.state === "error") toast("err", "La secuencia falló, revisa el registro");
    ui.progressState = progress.state;
  }
}

function renderDecision(decision) {
  if (!decision) {
    if (ui.modal === "decision") closeModal();
    return;
  }
  if (decision.id === ui.decisionId) return;
  ui.decisionId = decision.id;
  openModal("decision", `<h2><span class="dot err"></span><span id="decisionTitle"></span></h2>
    <div class="reason" id="decisionReason"></div>
    <p>Si el robot está en parada protectiva, desbloquéalo en el teach pendant antes de reintentar.</p>
    <div class="actions">
      <button class="btn danger" data-option="x">Cancelar</button>
      <button class="btn" data-option="s">Empezar de nuevo</button>
      <button class="btn primary" data-option="r">Reintentar punto ${decision.point}</button>
    </div>`);
  $("decisionTitle").textContent = `Secuencia detenida en el punto ${decision.point} de ${decision.total}`;
  $("decisionReason").textContent = decision.reason || "Revisa el registro para ver el motivo.";
  document.querySelectorAll("#modalBody [data-option]").forEach(button => {
    button.onclick = () => action(async () => {
      await api("/api/ensenar/decision", { option: button.dataset.option });
      closeModal();
    }, button);
  });
}

function stamp() {
  const date = new Date(), pad = n => String(n).padStart(2, "0");
  return `secuencia_${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(date.getDate())}_${pad(date.getHours())}${pad(date.getMinutes())}${pad(date.getSeconds())}.json`;
}

function openSave(thenRun) {
  if (!ui.teach.points.length) { toast("err", "No hay puntos que guardar"); return; }
  const host = grabHost();
  if (!host) return;
  openModal("save", `<h2>Guardar secuencia</h2>
    <p>Se guardará en la carpeta <code>data/</code>. Si el archivo ya existe tendrás que elegir otro nombre.</p>
    <label class="field">Nombre del archivo<input class="input" id="fileName" value="${stamp()}"></label>
    <div class="actions"><button class="btn ghost" id="saveCancel">Cancelar</button>
    <button class="btn primary" id="saveConfirm">${thenRun ? "Guardar y continuar" : "Guardar"}</button></div>`);
  $("fileName").select();
  $("saveCancel").onclick = closeModal;
  const confirm = $("saveConfirm");
  const save = () => action(async () => {
    const { name } = await api("/api/ensenar/guardar", { name: $("fileName").value.trim(), host });
    toast("ok", `Guardado en data/${name}`);
    closeModal();
    if (thenRun) confirmRun();
  }, confirm);
  confirm.onclick = save;
  $("fileName").onkeydown = event => event.key === "Enter" && save();
}

function confirmRun() {
  const host = executionHost();
  if (!host) return;
  openModal("confirm", `<h2><span class="dot warn"></span>Confirmar ejecución</h2>
    <p>El robot <b id="confirmHost" style="color:var(--text);font-family:var(--mono)"></b> se moverá desde su posición actual
    hasta el punto 1 y después recorrerá los ${ui.teach.points.length} puntos.</p>
    <p>Comprueba que la zona de trabajo está despejada.</p>
    <div class="actions"><button class="btn ghost" id="runCancel">Cancelar</button>
    <button class="btn primary" id="runConfirm">Empezar</button></div>`);
  $("confirmHost").textContent = host;
  $("runCancel").onclick = closeModal;
  const start = $("runConfirm");
  start.onclick = () => action(async () => {
    await api("/api/ensenar/ejecutar", { host });
    closeModal();
  }, start);
}

function openLoad(button) {
  return action(async () => {
    const { files } = await api("/api/ensenar/secuencias");
    openModal("load", `<h2>Cargar secuencia</h2>
      <p>Secuencias guardadas en la carpeta <code>data/</code>.</p>
      <div class="file-list" id="fileList"></div>
      <div class="actions"><button class="btn ghost" id="loadCancel">Cerrar</button></div>`);
    $("loadCancel").onclick = closeModal;
    const list = $("fileList");
    if (!files.length) list.innerHTML = `<div class="empty"><b>No hay secuencias</b>Guarda una para poder cargarla.</div>`;
    for (const file of files) {
      const row = document.createElement("button");
      row.className = "btn file-row";
      row.innerHTML = `<span></span><span class="muted"></span>`;
      row.firstChild.textContent = file.name;
      row.lastChild.textContent = file.modified;
      row.onclick = () => action(async () => {
        const { host } = await api("/api/ensenar/cargar", { name: file.name });
        if (!$("grabHost").value.trim()) $("grabHost").value = host;
        closeModal();
        toast("ok", `Secuencia ${file.name} cargada`);
      }, row);
      list.appendChild(row);
    }
  }, button);
}

function viewInVisualizer(button) {
  const host = grabHost();
  if (!host) return;
  return action(async () => {
    await api("/api/visualizador/abrir", {});
    if (!ui.hosts.some(entry => entry.host === host)) {
      await api("/api/hosts/anadir", { host, interface: "primaria" });
    }
    toast("ok", `Robot ${host} visible en el visualizador`);
  }, button);
}

/* ======================= EVENTS ======================= */
document.querySelectorAll("#nav button").forEach(button => button.onclick = () => showPage(button.dataset.page));
document.querySelectorAll("[data-monitor]").forEach(card => card.onclick = () => {
  setInterface(card.dataset.monitor);
  showPage("monitor");
  $("hostInput").focus();
});
document.querySelector("[data-page-link]").onclick = () => showPage("teach");
document.querySelectorAll("#ifaceSeg button").forEach(button => button.onclick = () => setInterface(button.dataset.iface));
document.querySelectorAll("[data-clear]").forEach(button => button.onclick = () => $("log-" + button.dataset.clear).innerHTML = "");

$("vizBtnTop").onclick = event => openVisualizer(event.currentTarget);
$("vizBtnBanner").onclick = event => openVisualizer(event.currentTarget);
$("addForm").onsubmit = event => {
  event.preventDefault();
  const input = $("hostInput");
  const host = requireHost(input, "Introduce una dirección IP válida");
  if (host) addHost(host, ui.iface, event.submitter).then(added => { if (added) input.value = ""; });
};
$("grabBtn").onclick = event => {
  const host = grabHost();
  if (host) action(() => api("/api/ensenar/capturar", { host }), event.currentTarget);
};
$("saveBtn").onclick = () => openSave(false);
$("loadBtn").onclick = event => openLoad(event.currentTarget);
$("runBtn").onclick = () => ui.teach.saved_as ? confirmRun() : openSave(true);
$("viewBtn").onclick = event => viewInVisualizer(event.currentTarget);
$("modal").onclick = event => { if (event.target === $("modal") && closableModal()) closeModal(); };
document.addEventListener("keydown", event => { if (event.key === "Escape" && closableModal()) closeModal(); });

poll();
