// local-movie-cast frontend

const state = {
  devices: [],
  activeDeviceUuid: null,
  currentPath: "",
  selectedFile: null,        // {path, name}
  selectedTileEl: null,
  selectedAudio: 0,
  tracks: [],
  savedPosition: null,       // секунд, если фильм был приостановлен
};

const els = {
  devices: document.getElementById("devices"),
  crumbs: document.getElementById("crumbs"),
  folders: document.getElementById("folders"),
  files: document.getElementById("files"),
  empty: document.getElementById("empty"),
  recentSection: document.getElementById("recent-section"),
  recent: document.getElementById("recent"),
  fileTitle: document.getElementById("file-title"),
  fileMeta: document.getElementById("file-meta"),
  tracksTitle: document.querySelector(".tracks-title"),
  tracks: document.getElementById("tracks"),
  castControls: document.getElementById("cast-controls"),
  sheetBackdrop: document.getElementById("sheet-backdrop"),
  sheetClose: document.getElementById("sheet-close"),
};

function openSheet() { document.body.classList.add("sheet-open"); }
function closeSheet() { document.body.classList.remove("sheet-open"); }
els.sheetClose.onclick = closeSheet;
els.sheetBackdrop.onclick = closeSheet;

// --- helpers ----------------------------------------------------------------

function fmtSize(b) {
  if (b == null) return "";
  const u = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  while (b >= 1024 && i < u.length - 1) { b /= 1024; i++; }
  return `${b.toFixed(b < 10 ? 1 : 0)} ${u[i]}`;
}

function fmtTime(s) {
  if (s == null) return "—";
  s = Math.round(s);
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), ss = s % 60;
  return h > 0
    ? `${h}:${String(m).padStart(2,"0")}:${String(ss).padStart(2,"0")}`
    : `${m}:${String(ss).padStart(2,"0")}`;
}

async function api(method, url, body) {
  const opts = { method };
  if (body !== undefined) {
    opts.headers = { "Content-Type": "application/json" };
    opts.body = JSON.stringify(body);
  }
  const r = await fetch(url, opts);
  if (!r.ok) {
    let msg = `${r.status}`;
    try { const j = await r.json(); msg = j.detail || msg; } catch {}
    throw new Error(msg);
  }
  return r.json();
}

// --- modal dialog -----------------------------------------------------------

function showDialog(message, type) {
  const modal = document.getElementById("modal");
  if (!modal) { console.error(message); return; }
  const t = type === "error" ? "error" : "info";
  modal.className = "modal modal-" + t;
  modal.querySelector(".modal-icon").textContent = t === "error" ? "error" : "info";
  modal.querySelector(".modal-title").textContent = t === "error" ? "Ошибка" : "";
  modal.querySelector(".modal-title").hidden = t !== "error";
  modal.querySelector(".modal-message").textContent = message;
  if (typeof modal.showModal === "function") {
    if (!modal.open) modal.showModal();
  } else {
    modal.setAttribute("open", "");
  }
}

(function initModal() {
  const modal = document.getElementById("modal");
  if (!modal) return;
  document.getElementById("modal-ok").onclick = () => modal.close();
  // Клик по бэкдропу (вне content) — закрываем.
  modal.addEventListener("click", (ev) => {
    const content = modal.querySelector(".modal-content");
    if (content && !content.contains(ev.target)) modal.close();
  });
})();

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));
}

function stripExt(name) {
  const i = name.lastIndexOf(".");
  return i > 0 ? name.slice(0, i) : name;
}

// --- devices ----------------------------------------------------------------

const DEVICE_ICONS = { cast: "cast", audio: "speaker", group: "speaker_group" };

function mi(name) {
  return `<span class="material-symbols-outlined">${name}</span>`;
}
const TYPE_ORDER = { cast: 0, group: 1, audio: 2 };

function sortedDevices() {
  return [...state.devices].sort((a, b) => {
    const ta = TYPE_ORDER[a.cast_type] ?? 9;
    const tb = TYPE_ORDER[b.cast_type] ?? 9;
    if (ta !== tb) return ta - tb;
    return (a.name || "").localeCompare(b.name || "");
  });
}

function deviceStatusHtml(d) {
  if (d.our_file) {
    const mode = `<span class="mode ${d.our_mode}">${d.our_mode}</span>`;
    const pos = (d.position != null && d.duration)
      ? ` · ${fmtTime(d.position)} / ${fmtTime(d.duration)}`
      : "";
    const fname = d.our_file.split("/").pop();
    return `${escapeHtml(fname)} ${mode}${pos}`;
  }
  if (d.app && d.app !== "Backdrop" && d.app !== "Default Media Receiver") {
    return `Занят: ${escapeHtml(d.app)}`;
  }
  return "Idle";
}

function renderDevices() {
  els.devices.innerHTML = "";
  for (const d of sortedDevices()) {
    const tab = document.createElement("div");
    tab.className = `device-tab type-${d.cast_type || "cast"}`;
    if (d.uuid === state.activeDeviceUuid) tab.classList.add("active");

    const stateLower = (d.state || "").toLowerCase();
    if (stateLower === "playing") tab.classList.add("playing");
    else if (stateLower === "paused") tab.classList.add("paused");

    const ourApp = d.our_file != null;
    if (!ourApp && d.app && d.app !== "Backdrop" && d.app !== "Default Media Receiver") {
      tab.classList.add("other-app");
    }

    const iconName = DEVICE_ICONS[d.cast_type] || "cast";

    const head = `<div class="dev-head">
      <span class="dot"></span>
      <span class="icon">${mi(iconName)}</span>
      <span class="name">${escapeHtml(d.name)}</span>
    </div>`;
    const model = `<div class="dev-model">${escapeHtml(d.model || d.cast_type || "")}</div>`;
    const status = `<div class="dev-status">${deviceStatusHtml(d)}</div>`;

    let controls = "";
    if (d.our_file) {
      const playing = (d.state || "").toUpperCase() === "PLAYING";
      const playBtnIcon = playing ? "pause" : "play_arrow";
      const playBtnTitle = playing ? "Пауза" : "Играть";
      const playBtnAction = playing ? "pause" : "play";
      controls = `
        <div class="dev-controls">
          <button class="dev-play" data-action="${playBtnAction}" title="${playBtnTitle}">${mi(playBtnIcon)}</button>
          <button class="dev-stop" title="Остановить">${mi("close")}</button>
        </div>`;
    }

    tab.innerHTML = head + model + status + controls;

    tab.onclick = (ev) => {
      if (ev.target.closest(".dev-controls")) return;
      state.activeDeviceUuid = d.uuid;
      renderDevices();
      refreshCastingHighlights();
      syncSavedPositionFromDevices();
      renderCastControls();
    };
    const stop = tab.querySelector(".dev-stop");
    if (stop) stop.onclick = (ev) => { ev.stopPropagation(); stopDevice(d.uuid); };
    const play = tab.querySelector(".dev-play");
    if (play) play.onclick = (ev) => {
      ev.stopPropagation();
      controlDevice(d.uuid, play.dataset.action);
    };

    els.devices.appendChild(tab);
  }
  if (!state.activeDeviceUuid && state.devices.length > 0) {
    state.activeDeviceUuid = sortedDevices()[0].uuid;
    renderDevices();
  }
  renderCastControls();
}

async function stopDevice(uuid) {
  try { await api("POST", "/api/stop", { device_uuid: uuid }); }
  catch (e) { showDialog(e.message, "error"); }
}

async function controlDevice(uuid, action) {
  try { await api("POST", "/api/control", { device_uuid: uuid, action }); }
  catch (e) { showDialog(e.message, "error"); }
}

// --- browser ----------------------------------------------------------------

async function loadDir(path) {
  state.currentPath = path;
  clearSelection();
  const data = await api("GET", `/api/browse?path=${encodeURIComponent(path)}`);
  renderListing(data);
  if (!path) loadRecent();
  else els.recentSection.hidden = true;
}

function clearSelection() {
  state.selectedFile = null;
  state.selectedTileEl = null;
  state.tracks = [];
  state.selectedAudio = 0;
  state.savedPosition = null;
  els.fileTitle.textContent = "Выбери файл";
  els.fileMeta.textContent = "";
  els.tracks.innerHTML = "";
  els.tracksTitle.hidden = true;
  renderCastControls();
}

async function loadRecent() {
  try {
    const items = await api("GET", "/api/recent");
    renderRecent(items);
  } catch {
    els.recentSection.hidden = true;
  }
}

function renderRecent(items) {
  els.recent.innerHTML = "";
  if (!items.length) { els.recentSection.hidden = true; return; }
  els.recentSection.hidden = false;
  for (const it of items) {
    const tile = document.createElement("div");
    tile.className = "recent-tile";
    tile.title = it.name;
    tile.dataset.path = it.path;
    tile.innerHTML = `
      <div class="thumb">
        <img loading="lazy" alt="" src="/api/thumb?path=${encodeURIComponent(it.path)}">
        <span class="now-playing material-symbols-outlined">play_arrow</span>
        <button class="recent-remove" title="Убрать из недавнего">${mi("close")}</button>
      </div>
      <div class="caption">${escapeHtml(stripExt(it.name))}</div>
    `;
    tile.onclick = (ev) => {
      if (ev.target.closest(".recent-remove")) return;
      castRecent(it);
    };
    tile.querySelector(".recent-remove").onclick = async (ev) => {
      ev.stopPropagation();
      await removeRecent(it.path);
    };
    els.recent.appendChild(tile);
  }
  refreshCastingHighlights();
}

async function removeRecent(path) {
  try {
    await api("DELETE", `/api/recent?path=${encodeURIComponent(path)}`);
    await loadRecent();
  } catch (e) {
    showDialog(e.message, "error");
  }
}

async function castRecent(item) {
  if (!state.activeDeviceUuid) {
    showDialog("Сначала выбери устройство");
    return;
  }
  try {
    await api("POST", "/api/cast", {
      device_uuid: state.activeDeviceUuid,
      path: item.path,
      audio_index: item.audio_index ?? 0,
    });
  } catch (e) {
    showDialog(`Не удалось: ${e.message}`, "error");
  }
}

function renderCrumbs(currentPath) {
  els.crumbs.innerHTML = "";
  const root = document.createElement("a");
  root.textContent = "media_root";
  root.onclick = () => loadDir("");
  els.crumbs.appendChild(root);
  if (!currentPath) return;
  const parts = currentPath.split("/");
  let acc = "";
  for (const p of parts) {
    acc = acc ? `${acc}/${p}` : p;
    els.crumbs.appendChild(document.createTextNode(" / "));
    const a = document.createElement("a");
    a.textContent = p;
    const target = acc;
    a.onclick = () => loadDir(target);
    els.crumbs.appendChild(a);
  }
}

function renderListing(data) {
  renderCrumbs(data.path);

  els.folders.innerHTML = "";
  if (data.parent != null) {
    const up = document.createElement("div");
    up.className = "folder up";
    up.innerHTML = `<span class="icon">${mi("arrow_upward")}</span><span>..</span>`;
    up.onclick = () => loadDir(data.parent);
    els.folders.appendChild(up);
  }
  for (const d of data.dirs) {
    const div = document.createElement("div");
    div.className = "folder";
    div.title = d.name;
    div.innerHTML = `<span class="icon">${mi("folder")}</span><span>${escapeHtml(d.name)}</span>`;
    div.onclick = () => loadDir(d.path);
    els.folders.appendChild(div);
  }
  els.folders.style.display = (data.dirs.length || data.parent != null) ? "" : "none";

  els.files.innerHTML = "";
  for (const f of data.files) {
    els.files.appendChild(makeTile(f));
  }

  els.empty.hidden = !(data.dirs.length === 0 && data.files.length === 0 && data.parent == null);
  refreshCastingHighlights();
}

function castingPaths() {
  const set = new Set();
  for (const d of state.devices) {
    if (d.our_file) set.add(d.our_file);
  }
  return set;
}

function refreshCastingHighlights() {
  const paths = castingPaths();
  document.querySelectorAll(".tile[data-path], .recent-tile[data-path]").forEach(el => {
    el.classList.toggle("casting", paths.has(el.dataset.path));
  });
}

function makeTile(f) {
  const tile = document.createElement("div");
  tile.className = "tile";
  tile.title = f.name;
  tile.dataset.path = f.path;

  const thumb = document.createElement("div");
  thumb.className = "thumb loading";

  const img = document.createElement("img");
  img.loading = "lazy";
  img.alt = "";
  img.onload = () => thumb.classList.remove("loading");
  img.onerror = () => { thumb.classList.remove("loading"); thumb.innerHTML = mi("movie"); img.remove(); };
  img.src = `/api/thumb?path=${encodeURIComponent(f.path)}`;
  thumb.appendChild(img);

  const np = document.createElement("span");
  np.className = "now-playing material-symbols-outlined";
  np.textContent = "play_arrow";
  thumb.appendChild(np);

  const caption = document.createElement("div");
  caption.className = "caption";
  const name = document.createElement("span");
  name.textContent = stripExt(f.name);
  const size = document.createElement("span");
  size.className = "size";
  size.textContent = fmtSize(f.size);
  caption.appendChild(name);
  caption.appendChild(size);

  tile.appendChild(thumb);
  tile.appendChild(caption);
  tile.onclick = () => selectFile(f, tile);
  return tile;
}

async function selectFile(f, tileEl) {
  state.selectedFile = f;
  state.savedPosition = null;
  if (state.selectedTileEl) state.selectedTileEl.classList.remove("selected");
  tileEl.classList.add("selected");
  state.selectedTileEl = tileEl;
  openSheet();

  els.fileTitle.textContent = stripExt(f.name);
  els.fileMeta.textContent = "Читаю дорожки…";
  els.tracks.innerHTML = "";
  els.tracksTitle.hidden = true;
  renderCastControls();

  try {
    const [data, posData] = await Promise.all([
      api("GET", `/api/tracks?path=${encodeURIComponent(f.path)}`),
      api("GET", `/api/position?path=${encodeURIComponent(f.path)}`).catch(() => ({ position: null })),
    ]);
    state.tracks = data.tracks;
    state.selectedAudio = 0;
    state.savedPosition = posData.position;
    const parts = [data.video_codec || "?"];
    if (data.width && data.height) parts.push(`${data.width}×${data.height}`);
    parts.push(fmtTime(data.duration));
    parts.push(`${data.tracks.length} аудиодорожек`);
    els.fileMeta.textContent = parts.join(" · ");
    renderTracks();
    renderCastControls();
  } catch (e) {
    els.fileMeta.textContent = `Ошибка: ${e.message}`;
  }
}

function renderTracks() {
  els.tracksTitle.hidden = state.tracks.length === 0;
  els.tracks.innerHTML = "";
  state.tracks.forEach((t, i) => {
    const li = document.createElement("li");
    if (i === state.selectedAudio) li.classList.add("selected");
    const lang = t.lang || "und";
    const title = t.title ? ` — ${escapeHtml(t.title)}` : "";
    const ch = t.channels ? ` ${t.channels}ch` : "";
    li.innerHTML = `<strong>${escapeHtml(lang)}</strong>${title}<span class="codec">${escapeHtml(t.codec)}${ch}</span>`;
    li.onclick = () => { state.selectedAudio = i; renderTracks(); };
    els.tracks.appendChild(li);
  });
}

function renderCastControls() {
  const canCast = state.selectedFile && state.activeDeviceUuid && state.tracks.length > 0;
  els.castControls.innerHTML = "";

  if (!canCast) {
    const btn = document.createElement("button");
    btn.className = "cast-btn";
    btn.disabled = true;
    btn.innerHTML = `${mi("cast")}<span class="cast-label">Транслировать</span>`;
    els.castControls.appendChild(btn);
    return;
  }

  // Если выбранный файл сейчас играет — показываем компактный «now playing»
  // блок вместо кнопок каста.
  const castingDevice = state.devices.find(d => d.our_file === state.selectedFile.path);
  if (castingDevice) {
    const stateLower = (castingDevice.state || "").toLowerCase();
    const icon = stateLower === "paused" ? "pause" : "play_arrow";
    const pos = castingDevice.position != null ? fmtTime(castingDevice.position) : "—";
    const dur = castingDevice.duration ? fmtTime(castingDevice.duration) : "—";
    const verb = stateLower === "paused" ? "На паузе на" : "Транслируется на";

    const box = document.createElement("div");
    box.className = "cast-status-box";
    box.innerHTML = `
      <div class="cast-status-line">${mi(icon)}<span>${verb} ${escapeHtml(castingDevice.name)}</span></div>
      <div class="cast-status-time">${pos} / ${dur}</div>
    `;
    els.castControls.appendChild(box);

    const stop = document.createElement("button");
    stop.className = "cast-btn-outlined";
    stop.innerHTML = `${mi("stop")}<span class="cast-label">Остановить</span>`;
    stop.onclick = () => stopDevice(castingDevice.uuid);
    els.castControls.appendChild(stop);
    return;
  }

  const pos = state.savedPosition;
  if (pos && pos > 5) {
    const resume = document.createElement("button");
    resume.className = "cast-btn";
    resume.innerHTML = `${mi("play_arrow")}<span class="cast-label">Продолжить с ${fmtTime(pos)}</span>`;
    resume.onclick = () => doCast(pos);
    els.castControls.appendChild(resume);

    const restart = document.createElement("button");
    restart.className = "cast-btn-outlined";
    restart.innerHTML = `${mi("restart_alt")}<span class="cast-label">Сначала</span>`;
    restart.onclick = () => doCast(0);
    els.castControls.appendChild(restart);
  } else {
    const btn = document.createElement("button");
    btn.className = "cast-btn";
    btn.innerHTML = `${mi("cast")}<span class="cast-label">Транслировать</span>`;
    btn.onclick = () => doCast(0);
    els.castControls.appendChild(btn);
  }
}

function syncSavedPositionFromDevices() {
  // Если выбранный файл сейчас играет, держим savedPosition синхронным с
  // SSE-апдейтами — чтобы кнопка «Продолжить с …» (когда фильм будет
  // остановлен) показывала свежее значение.
  if (!state.selectedFile) return;
  const dev = state.devices.find(d => d.our_file === state.selectedFile.path);
  if (dev && dev.position != null && dev.position > 0) {
    state.savedPosition = dev.position;
  }
}

async function doCast(startSeconds) {
  if (!state.selectedFile || !state.activeDeviceUuid) return;
  for (const b of els.castControls.querySelectorAll("button")) b.disabled = true;
  try {
    // «Сначала» подразумевает очистку сохранённой позиции — иначе она перепишется
    // в первые секунды от status-апдейтов до того, как фильм отыграет дальше.
    if (startSeconds === 0 && state.savedPosition) {
      await api("DELETE", `/api/position?path=${encodeURIComponent(state.selectedFile.path)}`).catch(() => {});
      state.savedPosition = null;
    }
    await api("POST", "/api/cast", {
      device_uuid: state.activeDeviceUuid,
      path: state.selectedFile.path,
      audio_index: state.selectedAudio,
      start_seconds: startSeconds,
    });
    if (!state.currentPath) loadRecent();
    closeSheet();
  } catch (e) {
    showDialog(`Не удалось: ${e.message}`, "error");
  } finally {
    renderCastControls();
  }
}

// --- SSE --------------------------------------------------------------------

function connectStatus() {
  const es = new EventSource("/api/status/stream");
  es.onmessage = (ev) => {
    if (!ev.data) return;
    const msg = JSON.parse(ev.data);
    if (msg.type === "snapshot") {
      state.devices = msg.devices;
      renderDevices();
      refreshCastingHighlights();
      syncSavedPositionFromDevices();
      renderCastControls();
    } else if (msg.type === "update") {
      const idx = state.devices.findIndex(d => d.uuid === msg.device.uuid);
      if (idx >= 0) {
        state.devices[idx] = { ...state.devices[idx], ...msg.device };
      } else {
        state.devices.push(msg.device);
      }
      renderDevices();
      refreshCastingHighlights();
      syncSavedPositionFromDevices();
      renderCastControls();
    }
  };
  es.onerror = () => {
    es.close();
    setTimeout(connectStatus, 2000);
  };
}

// --- view mode (grid / list) ------------------------------------------------

function applyView(mode) {
  const m = mode === "list" ? "list" : "grid";
  els.files.dataset.view = m;
  document.getElementById("view-grid").classList.toggle("active", m === "grid");
  document.getElementById("view-list").classList.toggle("active", m === "list");
}

function setView(mode) {
  localStorage.setItem("view", mode);
  applyView(mode);
}

document.getElementById("view-grid").onclick = () => setView("grid");
document.getElementById("view-list").onclick = () => setView("list");
applyView(localStorage.getItem("view") || "grid");

// --- theme ------------------------------------------------------------------

const THEME_ICONS = { dark: "light_mode", light: "dark_mode" };

function applyThemeButton() {
  const t = document.documentElement.getAttribute("data-theme") || "dark";
  const btn = document.getElementById("theme-toggle");
  if (!btn) return;
  const icon = btn.querySelector(".material-symbols-outlined");
  if (icon) icon.textContent = THEME_ICONS[t];
}

function toggleTheme() {
  const cur = document.documentElement.getAttribute("data-theme") || "dark";
  const next = cur === "dark" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", next);
  localStorage.setItem("theme", next);
  applyThemeButton();
}

document.getElementById("theme-toggle").onclick = toggleTheme;
applyThemeButton();

// --- version ----------------------------------------------------------------

async function loadVersion() {
  try {
    const r = await fetch("/api/version");
    const data = await r.json();
    const el = document.getElementById("app-version");
    if (el && data.version) el.textContent = "v" + data.version;
  } catch {}
}

// --- boot -------------------------------------------------------------------

loadDir("").catch(e => {
  els.files.innerHTML = `<div class="empty">Ошибка: ${escapeHtml(e.message)}</div>`;
});
connectStatus();
loadVersion();
