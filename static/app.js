// local-movie-cast frontend

const state = {
  devices: [],
  activeDeviceUuid: null,
  currentPath: "",
  selectedFile: null,        // {path, name}
  selectedTileEl: null,
  selectedAudio: 0,
  tracks: [],
};

const els = {
  devices: document.getElementById("devices"),
  crumbs: document.getElementById("crumbs"),
  folders: document.getElementById("folders"),
  files: document.getElementById("files"),
  empty: document.getElementById("empty"),
  fileTitle: document.getElementById("file-title"),
  fileMeta: document.getElementById("file-meta"),
  tracksTitle: document.querySelector(".tracks-title"),
  tracks: document.getElementById("tracks"),
  castBtn: document.getElementById("cast-btn"),
};

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
  refreshCastButton();
}

async function stopDevice(uuid) {
  try { await api("POST", "/api/stop", { device_uuid: uuid }); }
  catch (e) { alert(e.message); }
}

async function controlDevice(uuid, action) {
  try { await api("POST", "/api/control", { device_uuid: uuid, action }); }
  catch (e) { alert(e.message); }
}

// --- browser ----------------------------------------------------------------

async function loadDir(path) {
  state.currentPath = path;
  const data = await api("GET", `/api/browse?path=${encodeURIComponent(path)}`);
  renderListing(data);
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
}

function makeTile(f) {
  const tile = document.createElement("div");
  tile.className = "tile";
  tile.title = f.name;

  const thumb = document.createElement("div");
  thumb.className = "thumb loading";

  const img = document.createElement("img");
  img.loading = "lazy";
  img.alt = "";
  img.onload = () => thumb.classList.remove("loading");
  img.onerror = () => { thumb.classList.remove("loading"); thumb.innerHTML = mi("movie"); img.remove(); };
  img.src = `/api/thumb?path=${encodeURIComponent(f.path)}`;
  thumb.appendChild(img);

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
  if (state.selectedTileEl) state.selectedTileEl.classList.remove("selected");
  tileEl.classList.add("selected");
  state.selectedTileEl = tileEl;

  els.fileTitle.textContent = stripExt(f.name);
  els.fileMeta.textContent = "Читаю дорожки…";
  els.tracks.innerHTML = "";
  els.tracksTitle.hidden = true;
  els.castBtn.disabled = true;

  try {
    const data = await api("GET", `/api/tracks?path=${encodeURIComponent(f.path)}`);
    state.tracks = data.tracks;
    state.selectedAudio = 0;
    els.fileMeta.textContent = `${data.video_codec || "?"} · ${fmtTime(data.duration)} · ${data.tracks.length} аудиодорожек`;
    renderTracks();
    refreshCastButton();
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

function refreshCastButton() {
  els.castBtn.disabled = !(state.selectedFile && state.activeDeviceUuid && state.tracks.length > 0);
}

// --- cast / stop ------------------------------------------------------------

els.castBtn.onclick = async () => {
  if (!state.selectedFile || !state.activeDeviceUuid) return;
  els.castBtn.disabled = true;
  els.castBtn.textContent = "Запускаю…";
  try {
    await api("POST", "/api/cast", {
      device_uuid: state.activeDeviceUuid,
      path: state.selectedFile.path,
      audio_index: state.selectedAudio,
    });
  } catch (e) {
    alert(`Не удалось: ${e.message}`);
  } finally {
    els.castBtn.disabled = false;
    els.castBtn.textContent = "Кастить";
  }
};

// --- SSE --------------------------------------------------------------------

function connectStatus() {
  const es = new EventSource("/api/status/stream");
  es.onmessage = (ev) => {
    if (!ev.data) return;
    const msg = JSON.parse(ev.data);
    if (msg.type === "snapshot") {
      state.devices = msg.devices;
      renderDevices();
    } else if (msg.type === "update") {
      const idx = state.devices.findIndex(d => d.uuid === msg.device.uuid);
      if (idx >= 0) {
        state.devices[idx] = { ...state.devices[idx], ...msg.device };
      } else {
        state.devices.push(msg.device);
      }
      renderDevices();
    }
  };
  es.onerror = () => {
    es.close();
    setTimeout(connectStatus, 2000);
  };
}

// --- boot -------------------------------------------------------------------

loadDir("").catch(e => {
  els.files.innerHTML = `<div class="empty">Ошибка: ${escapeHtml(e.message)}</div>`;
});
connectStatus();
