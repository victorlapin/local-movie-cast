// local-movie-cast frontend

const state = {
  devices: [],
  activeDeviceUuid: null,
  currentPath: "",
  selectedFile: null,        // {path, name}
  selectedAudio: 0,
  tracks: [],
};

const els = {
  devices: document.getElementById("devices"),
  crumbs: document.getElementById("crumbs"),
  listing: document.getElementById("listing"),
  fileTitle: document.getElementById("file-title"),
  fileMeta: document.getElementById("file-meta"),
  tracksTitle: document.querySelector(".tracks-title"),
  tracks: document.getElementById("tracks"),
  castBtn: document.getElementById("cast-btn"),
  stopBtn: document.getElementById("stop-btn"),
  statusBar: document.getElementById("status-bar"),
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

// --- devices ----------------------------------------------------------------

function renderDevices() {
  els.devices.innerHTML = "";
  for (const d of state.devices) {
    const tab = document.createElement("div");
    tab.className = "device-tab";
    if (d.uuid === state.activeDeviceUuid) tab.classList.add("active");

    const stateLower = (d.state || "").toLowerCase();
    if (stateLower === "playing") tab.classList.add("playing");
    else if (stateLower === "paused") tab.classList.add("paused");

    // активное приложение — наш каст или чужое?
    const ourApp = d.our_file != null;
    if (!ourApp && d.app && d.app !== "Backdrop" && d.app !== "Default Media Receiver") {
      tab.classList.add("other-app");
    }

    tab.innerHTML = `<span class="dot"></span><span>${escapeHtml(d.name)}</span>`;
    tab.onclick = () => { state.activeDeviceUuid = d.uuid; renderDevices(); renderStatus(); };
    els.devices.appendChild(tab);
  }
  if (!state.activeDeviceUuid && state.devices.length > 0) {
    state.activeDeviceUuid = state.devices[0].uuid;
    renderDevices();
  }
  refreshCastButton();
}

function renderStatus() {
  const d = state.devices.find(x => x.uuid === state.activeDeviceUuid);
  if (!d) { els.statusBar.textContent = "Нет устройства"; els.stopBtn.hidden = true; return; }

  let html = `<strong>${escapeHtml(d.name)}</strong>: `;
  if (d.our_file) {
    html += `Играю ${escapeHtml(d.our_file)} `;
    html += `<span class="mode ${d.our_mode}">${d.our_mode}</span>`;
    if (d.our_audio_lang || d.our_audio_codec) {
      html += ` · ${escapeHtml(d.our_audio_lang || "")} ${escapeHtml(d.our_audio_codec || "")}`;
    }
    if (d.position != null && d.duration) {
      html += ` · ${fmtTime(d.position)} / ${fmtTime(d.duration)}`;
    }
    els.stopBtn.hidden = false;
  } else if (d.app && d.app !== "Backdrop" && d.app !== "Default Media Receiver") {
    html += `Занят: ${escapeHtml(d.app)}`;
    els.stopBtn.hidden = true;
  } else {
    html += "Idle";
    els.stopBtn.hidden = true;
  }
  els.statusBar.innerHTML = html;
}

// --- browser ----------------------------------------------------------------

async function loadDir(path) {
  state.currentPath = path;
  const data = await api("GET", `/api/browse?path=${encodeURIComponent(path)}`);
  renderListing(data);
}

function renderListing(data) {
  // breadcrumbs
  els.crumbs.innerHTML = "";
  const root = document.createElement("a");
  root.textContent = "media_root";
  root.onclick = () => loadDir("");
  els.crumbs.appendChild(root);
  if (data.path) {
    const parts = data.path.split("/");
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

  els.listing.innerHTML = "";
  for (const d of data.dirs) {
    const li = document.createElement("li");
    li.innerHTML = `<span class="icon">📁</span><span>${escapeHtml(d.name)}</span>`;
    li.onclick = () => loadDir(d.path);
    els.listing.appendChild(li);
  }
  for (const f of data.files) {
    const li = document.createElement("li");
    li.innerHTML = `<span class="icon">🎬</span><span>${escapeHtml(f.name)}</span><span class="size">${fmtSize(f.size)}</span>`;
    li.onclick = () => selectFile(f, li);
    els.listing.appendChild(li);
  }
}

async function selectFile(f, liEl) {
  state.selectedFile = f;
  for (const li of els.listing.querySelectorAll("li.selected")) li.classList.remove("selected");
  liEl.classList.add("selected");

  els.fileTitle.textContent = f.name;
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

els.stopBtn.onclick = async () => {
  if (!state.activeDeviceUuid) return;
  try { await api("POST", "/api/stop", { device_uuid: state.activeDeviceUuid }); }
  catch (e) { alert(e.message); }
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
      renderStatus();
    } else if (msg.type === "update") {
      const idx = state.devices.findIndex(d => d.uuid === msg.device.uuid);
      if (idx >= 0) {
        // сохраняем поля our_* — они приходят отдельно через snapshot
        state.devices[idx] = { ...state.devices[idx], ...msg.device };
      } else {
        state.devices.push(msg.device);
      }
      renderDevices();
      renderStatus();
    }
  };
  es.onerror = () => {
    es.close();
    setTimeout(connectStatus, 2000);
  };
}

// --- utils ------------------------------------------------------------------

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));
}

// --- boot -------------------------------------------------------------------

loadDir("").catch(e => { els.listing.innerHTML = `<li>Ошибка: ${e.message}</li>`; });
connectStatus();
