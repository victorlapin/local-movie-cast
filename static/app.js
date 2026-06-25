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
  librariesSection: document.getElementById("libraries-section"),
  libraries: document.getElementById("libraries"),
  searchInput: document.getElementById("search-input"),
  searchClear: document.getElementById("search-clear"),
  searchSection: document.getElementById("search-section"),
  searchStatus: document.getElementById("search-status"),
  searchResults: document.getElementById("search-results"),
  fileTitle: document.getElementById("file-title"),
  fileMeta: document.getElementById("file-meta"),
  tracksTitle: document.querySelector(".tracks-title"),
  tracks: document.getElementById("tracks"),
  castControls: document.getElementById("cast-controls"),
  revealBtn: document.getElementById("reveal-btn"),
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

// Каскадная задержка для stagger-анимации. Капаем на 12 элементах, чтобы
// в длинных списках последние не появлялись через секунду.
function staggerDelay(i) {
  return Math.min(i, 12) * 25 + "ms";
}

// Вставляет zero-width space после _ . -, чтобы браузер мог переносить длинные
// «From_Russia_with_love» по разделителям, а не одной кашей.
function softBreaks(s) {
  return String(s).replace(/([_.\-])/g, "$1​");
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

// --- search -----------------------------------------------------------------

let _searchDebounce = null;
let _searchSeq = 0;

els.searchInput.addEventListener("input", () => {
  els.searchClear.hidden = !els.searchInput.value;
  if (_searchDebounce) clearTimeout(_searchDebounce);
  _searchDebounce = setTimeout(runSearch, 400);
});

els.searchClear.onclick = () => {
  els.searchInput.value = "";
  els.searchClear.hidden = true;
  exitSearch();
  els.searchInput.focus();
};

async function runSearch() {
  const q = els.searchInput.value.trim();
  if (!q) { exitSearch(); return; }
  const mySeq = ++_searchSeq;
  try {
    const data = await api("GET", `/api/search?q=${encodeURIComponent(q)}`);
    if (mySeq !== _searchSeq) return; // пришёл устаревший ответ — игнорируем
    renderSearch(q, data);
  } catch (e) {
    if (mySeq !== _searchSeq) return;
    els.searchStatus.textContent = "Ошибка: " + e.message;
    els.searchResults.innerHTML = "";
    els.searchSection.hidden = false;
    hideBrowseSections();
  }
}

function hideBrowseSections() {
  els.recentSection.hidden = true;
  els.librariesSection.hidden = true;
  els.folders.style.display = "none";
  els.folders.innerHTML = "";
  els.files.innerHTML = "";
  els.empty.hidden = true;
  document.querySelector(".browser-bar").style.display = "none";
}

function showBrowseSections() {
  document.querySelector(".browser-bar").style.display = "";
}

function exitSearch() {
  _searchSeq++;
  els.searchSection.hidden = true;
  showBrowseSections();
  if (state.lastListing) renderListing(state.lastListing);
  if (!state.currentPath) loadRecent();
}

function renderSearch(query, data) {
  hideBrowseSections();
  els.searchSection.hidden = false;
  const limited = data.limited ? " (показано первые " + data.total + ")" : "";
  if (data.total === 0) {
    els.searchStatus.textContent = `Ничего не найдено по «${query}»`;
  } else {
    els.searchStatus.textContent = `Найдено ${data.total}${limited}`;
  }
  els.searchResults.innerHTML = "";
  // Применим режим из view-toggle и сортировку.
  els.searchResults.dataset.view = els.files.dataset.view || "grid";
  let si = 0;
  for (const f of sortFiles(data.results)) {
    const tile = makeTile(f);
    tile.style.animationDelay = staggerDelay(si++);
    // Подпишем папку, чтобы понятно, где файл лежит. lib_id из начала пути
    // убираем — для юзера это бессмысленный хэш.
    if (f.dir) {
      const slash = f.dir.indexOf("/");
      const displayDir = slash >= 0 ? f.dir.slice(slash + 1) : "";
      if (displayDir) {
        const caption = tile.querySelector(".caption");
        const sub = document.createElement("span");
        sub.className = "tile-subdir";
        sub.textContent = softBreaks(displayDir);
        caption.insertBefore(sub, caption.firstChild);
      }
    }
    els.searchResults.appendChild(tile);
  }
  refreshCastingHighlights();
}

// --- browser ----------------------------------------------------------------

async function loadDir(path) {
  state.currentPath = path;
  // Сохраняем путь в URL, чтобы F5/назад/вперёд работали корректно.
  const targetHash = path ? "#" + encodeURIComponent(path) : "";
  if (location.hash !== targetHash) {
    history.pushState(null, "", location.pathname + targetHash);
  }
  clearSelection();
  const data = await api("GET", `/api/browse?path=${encodeURIComponent(path)}`);
  state.lastListing = data;
  renderListing(data);
  if (!path) loadRecent();
  else els.recentSection.hidden = true;
}

function pathFromHash() {
  const h = location.hash;
  if (!h || h === "#") return "";
  try {
    return decodeURIComponent(h.slice(1));
  } catch {
    return "";
  }
}

// Бэк/вперёд браузера или ручное изменение URL.
window.addEventListener("hashchange", () => {
  const p = pathFromHash();
  if (p !== state.currentPath) loadDir(p).catch(() => {});
});

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
  els.revealBtn.hidden = true;
  renderCastControls();
}

els.revealBtn.onclick = async () => {
  if (!state.selectedFile) return;
  try {
    await api("POST", "/api/reveal", { path: state.selectedFile.path });
  } catch (e) {
    showDialog(e.message, "error");
  }
};

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
  let ri = 0;
  for (const it of items) {
    const tile = document.createElement("div");
    tile.className = "recent-tile";
    tile.style.animationDelay = staggerDelay(ri++);
    tile.title = it.name;
    tile.dataset.path = it.path;
    tile.innerHTML = `
      <div class="thumb loading">
        <img loading="lazy" alt="" src="/api/thumb?path=${encodeURIComponent(it.path)}">
        <span class="now-playing material-symbols-outlined">play_arrow</span>
        <button class="recent-remove" title="Убрать из недавнего">${mi("close")}</button>
      </div>
      <div class="caption">${escapeHtml(stripExt(it.name))}</div>
    `;
    const recImg = tile.querySelector(".thumb img");
    const recThumb = tile.querySelector(".thumb");
    recImg.onload = () => {
      recThumb.classList.remove("loading");
      recImg.classList.add("loaded");
    };
    tile.onclick = (ev) => {
      if (ev.target.closest(".recent-remove")) return;
      selectFile(it, tile);
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

  // Корень — рендерим библиотеки крупными карточками + плюс/удаление.
  if (data.path === "") {
    renderLibraries(data.dirs);
    els.folders.innerHTML = "";
    els.folders.style.display = "none";
    els.files.innerHTML = "";
    els.empty.hidden = true;
    return;
  }

  els.librariesSection.hidden = true;

  els.folders.innerHTML = "";
  let fi = 0;
  if (data.parent != null) {
    const up = document.createElement("div");
    up.className = "folder up";
    up.style.animationDelay = staggerDelay(fi++);
    up.innerHTML = `<span class="icon">${mi("arrow_upward")}</span><span>..</span>`;
    up.onclick = () => loadDir(data.parent);
    els.folders.appendChild(up);
  }
  for (const d of data.dirs) {
    const div = document.createElement("div");
    div.className = "folder";
    div.style.animationDelay = staggerDelay(fi++);
    div.title = d.name;
    div.innerHTML = `<span class="icon">${mi("folder")}</span><span>${escapeHtml(d.name)}</span>`;
    div.onclick = () => loadDir(d.path);
    els.folders.appendChild(div);
  }
  els.folders.style.display = (data.dirs.length || data.parent != null) ? "" : "none";

  els.files.innerHTML = "";
  let i = 0;
  for (const f of sortFiles(data.files)) {
    const tile = makeTile(f);
    tile.style.animationDelay = staggerDelay(i++);
    els.files.appendChild(tile);
  }

  els.empty.hidden = !(data.dirs.length === 0 && data.files.length === 0 && data.parent == null);
  refreshCastingHighlights();
}

function renderLibraries(libs) {
  els.librariesSection.hidden = false;
  els.libraries.innerHTML = "";
  let li = 0;
  for (const lib of libs) {
    const card = document.createElement("div");
    card.className = "library-card";
    card.style.animationDelay = staggerDelay(li++);
    card.title = lib.name;
    card.innerHTML = `
      <span class="icon material-symbols-outlined">folder_open</span>
      <span class="name">${escapeHtml(lib.name)}</span>
      <button class="library-remove" title="Убрать">${mi("close")}</button>
    `;
    card.onclick = (ev) => {
      if (ev.target.closest(".library-remove")) return;
      loadDir(lib.path);
    };
    card.querySelector(".library-remove").onclick = (ev) => {
      ev.stopPropagation();
      removeLibrary(lib.path, lib.name);
    };
    els.libraries.appendChild(card);
  }
  // Кнопка «+» добавления библиотеки
  const add = document.createElement("div");
  add.className = "library-card library-add";
  add.style.animationDelay = staggerDelay(li++);
  add.innerHTML = `<span class="icon material-symbols-outlined">add</span><span class="name">Добавить</span>`;
  add.onclick = openLibraryAddModal;
  els.libraries.appendChild(add);
}

function openLibraryAddModal() {
  const modal = document.getElementById("library-add-modal");
  const input = document.getElementById("library-add-path");
  input.value = "";
  if (typeof modal.showModal === "function") modal.showModal();
  else modal.setAttribute("open", "");
  setTimeout(() => input.focus(), 50);
}

(function initLibraryModal() {
  const modal = document.getElementById("library-add-modal");
  if (!modal) return;
  const form = document.getElementById("library-add-form");
  document.getElementById("library-add-cancel").onclick = () => modal.close();
  modal.addEventListener("click", (ev) => {
    const content = modal.querySelector(".modal-content");
    if (content && !content.contains(ev.target)) modal.close();
  });
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const path = document.getElementById("library-add-path").value.trim();
    if (!path) return;
    try {
      await api("POST", "/api/libraries", { path });
      modal.close();
      await loadDir("");
    } catch (e) {
      showDialog(e.message, "error");
    }
  });
})();

async function removeLibrary(libIdOrPath, name) {
  // libIdOrPath: путь в карточке = lib_id (просто idшник, не путь)
  if (!confirm(`Убрать «${name}» из списка библиотек?\n\nФайлы на диске НЕ удаляются.`)) return;
  try {
    await api("DELETE", `/api/libraries/${encodeURIComponent(libIdOrPath)}`);
    await loadDir("");
  } catch (e) {
    showDialog(e.message, "error");
  }
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
  img.onload = () => {
    thumb.classList.remove("loading");
    img.classList.add("loaded");
  };
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
  name.className = "tile-name";
  name.textContent = softBreaks(stripExt(f.name));
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
  els.revealBtn.hidden = false;
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

// --- sort -------------------------------------------------------------------

function getSortMode() {
  return localStorage.getItem("sort") || "name-asc";
}

function sortFiles(files) {
  const mode = getSortMode();
  const arr = [...files];
  // Группировка: латиница/цифры (0), кириллица (1), всё прочее (2).
  // Latin сначала при ascending, Cyrillic первым при descending.
  const nameGroup = (s) => {
    if (!s) return 9;
    const c = s.charCodeAt(0);
    if (c < 0x80) return 0;
    if (c >= 0x0400 && c <= 0x04FF) return 1;
    return 2;
  };
  const byName = (a, b) => {
    const ga = nameGroup(a.name);
    const gb = nameGroup(b.name);
    if (ga !== gb) return ga - gb;
    return (a.name || "").localeCompare(b.name || "", undefined, { numeric: true });
  };
  switch (mode) {
    case "name-desc": arr.sort((a, b) => byName(b, a)); break;
    case "date-desc": arr.sort((a, b) => (b.mtime || 0) - (a.mtime || 0)); break;
    case "date-asc":  arr.sort((a, b) => (a.mtime || 0) - (b.mtime || 0)); break;
    case "size-desc": arr.sort((a, b) => (b.size || 0) - (a.size || 0)); break;
    case "size-asc":  arr.sort((a, b) => (a.size || 0) - (b.size || 0)); break;
    case "name-asc":
    default:          arr.sort(byName); break;
  }
  return arr;
}

const sortSelect = document.getElementById("sort-select");
sortSelect.value = getSortMode();
sortSelect.onchange = () => {
  localStorage.setItem("sort", sortSelect.value);
  // Перерисуем текущую папку, не перегружая запросом.
  if (state.lastListing) renderListing(state.lastListing);
};

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

loadDir(pathFromHash()).catch(e => {
  els.files.innerHTML = `<div class="empty">Ошибка: ${escapeHtml(e.message)}</div>`;
});
connectStatus();
loadVersion();
