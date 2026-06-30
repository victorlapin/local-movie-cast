// Setup wizard logic

const els = {
  form: document.getElementById("setup-form"),
  mediaRoot: document.getElementById("media-root"),
  hostIp: document.getElementById("host-ip"),
  hostIpCustom: document.getElementById("host-ip-custom"),
  encoder: document.getElementById("encoder"),
  submit: document.getElementById("setup-submit"),
  submitLabel: document.querySelector("#setup-submit .cast-label"),
  error: document.getElementById("setup-error"),
  done: document.getElementById("setup-done"),
};

function showError(msg) {
  els.error.textContent = msg;
  els.error.hidden = false;
}

function clearError() {
  els.error.hidden = true;
}

async function loadInfo() {
  try {
    const r = await fetch("/api/setup/info");
    const info = await r.json();

    els.mediaRoot.value = info.default_media || "";

    const vEl = document.getElementById("app-version");
    if (vEl && info.version) vEl.textContent = "v" + info.version;

    els.hostIp.innerHTML = "";
    const list = info.interfaces.slice();
    // Поднимаем detected_ip в начало, если он есть в списке.
    if (info.detected_ip && list.includes(info.detected_ip)) {
      list.splice(list.indexOf(info.detected_ip), 1);
      list.unshift(info.detected_ip);
    } else if (info.detected_ip) {
      list.unshift(info.detected_ip);
    }
    for (const ip of list) {
      const opt = document.createElement("option");
      opt.value = ip;
      opt.textContent = ip + (ip === info.detected_ip ? " (определён авто)" : "");
      els.hostIp.appendChild(opt);
    }
    if (!list.length) {
      const opt = document.createElement("option");
      opt.value = "";
      opt.textContent = "Не нашёл интерфейсов — введи вручную";
      els.hostIp.appendChild(opt);
    }
  } catch (e) {
    showError("Не удалось получить данные о сети: " + e.message);
  }
}

els.form.onsubmit = async (ev) => {
  ev.preventDefault();
  clearError();

  const host_ip = (els.hostIpCustom.value || els.hostIp.value || "").trim();
  const media_root = els.mediaRoot.value.trim();
  const encoder = (els.encoder && els.encoder.value) || "h264_nvenc";

  if (!media_root) { showError("Укажи папку с фильмами"); return; }
  if (!host_ip)    { showError("Укажи IP машины"); return; }

  els.submit.disabled = true;
  if (els.submitLabel) els.submitLabel.textContent = "Сохраняю…";

  try {
    const r = await fetch("/api/setup/save", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({media_root, host_ip, encoder}),
    });
    if (!r.ok) {
      let msg = "Ошибка " + r.status;
      try { msg = (await r.json()).detail || msg; } catch {}
      throw new Error(msg);
    }
    // Автозапуск, если пользователь оставил галку (и фича реально доступна)
    const autoCb = document.getElementById("autostart-cb");
    if (autoCb && autoCb.checked && !autoCb.disabled) {
      try { await fetch("/api/autostart/enable", { method: "POST" }); } catch {}
    }

    els.form.hidden = true;
    els.done.hidden = false;
    // Soft-reload отработал внутри сервера — можно сразу на главную.
    setTimeout(() => { window.location.replace("/"); }, 600);
    // Дублирующая страховка на случай блокировки автонавигации.
    setTimeout(() => { window.location.reload(); }, 1800);
  } catch (e) {
    showError(e.message);
    els.submit.disabled = false;
    if (els.submitLabel) els.submitLabel.textContent = "Сохранить и запустить";
  }
};

async function checkAutostart() {
  const cb = document.getElementById("autostart-cb");
  const hint = document.getElementById("autostart-hint");
  try {
    const s = await fetch("/api/autostart/status").then(r => r.json());
    if (!s.supported) {
      cb.disabled = true;
      cb.checked = false;
      hint.textContent = "Доступно только в собранной версии (.exe). В режиме разработки игнорируется.";
    } else if (s.enabled) {
      cb.disabled = true;
      cb.checked = true;
      hint.textContent = "Автозапуск уже включён. Управлять можно через меню в трее.";
    }
  } catch {}
}

async function discoverDevices() {
  const el = document.getElementById("discovered");
  if (!el) return;
  try {
    const data = await fetch("/api/setup/discover").then(r => r.json());
    const devs = data.devices || [];
    if (!devs.length) {
      el.className = "discovered empty";
      el.innerHTML = "Не найдено ни одного устройства. Проверь, что Chromecast включён и компьютер в той же Wi-Fi сети.";
      return;
    }
    el.className = "discovered ok";
    const iconMap = { cast: "cast", audio: "speaker", group: "speaker_group" };
    el.innerHTML = devs.map(d => {
      const iconName = iconMap[d.cast_type] || "cast";
      const icon = `<span class="material-symbols-outlined">${iconName}</span>`;
      const model = d.model ? ` <span class="dev-model">${d.model}</span>` : "";
      return `<div class="discovered-item">${icon}<strong>${d.name}</strong>${model}</div>`;
    }).join("");
  } catch (e) {
    el.className = "discovered empty";
    el.textContent = "Не удалось проверить: " + e.message;
  }
}

loadInfo();
discoverDevices();
checkAutostart();
