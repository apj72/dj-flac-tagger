const $ = (sel) => document.querySelector(sel);

let selectedFile = null;

function esc(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

async function loadSettings() {
  const resp = await fetch("/api/settings");
  const cfg = await resp.json();
  const last = typeof djmmGetLastAudioBrowseDir === "function" ? djmmGetLastAudioBrowseDir().trim() : "";
  $("#ins-dir").value = last || cfg.destination_dir || "";
}

async function resetInspectDirToDefault() {
  await loadSettings();
  await browseFiles();
}

// ---- Server-side folder picker (same API as Fix / Bulk Fix) ----
let insFolderModalPath = "";

function closeInsFolderModal() {
  const el = document.getElementById("ins-folder-modal");
  if (el) el.classList.add("hidden");
  document.removeEventListener("keydown", onInsFolderModalKeydown);
}

function onInsFolderModalKeydown(e) {
  if (e.key === "Escape") closeInsFolderModal();
}

async function openInsFolderModal() {
  let start = $("#ins-dir").value.trim();
  if (!start) {
    const resp = await fetch("/api/settings");
    const cfg = await resp.json();
    start = (cfg.destination_dir || "").trim();
  }
  if (!start) start = "~";
  document.getElementById("ins-folder-modal").classList.remove("hidden");
  document.addEventListener("keydown", onInsFolderModalKeydown);
  await loadInsFolderInModal(start);
}

async function loadInsFolderInModal(path) {
  const listEl = $("#ins-modal-dir-list");
  const pathEl = $("#ins-modal-path");
  const upBtn = $("#ins-modal-up");
  listEl.innerHTML = '<div class="status">Loading…</div>';
  upBtn.disabled = true;

  const resp = await fetch(`/api/browse-folders?path=${encodeURIComponent(path)}`);
  const data = await resp.json();
  if (data.error) {
    listEl.innerHTML = `<div class="status">${esc(data.error)}</div>`;
    pathEl.textContent = path;
    insFolderModalPath = path;
    return;
  }
  insFolderModalPath = data.path;
  pathEl.textContent = data.path;
  if (data.parent) {
    upBtn.disabled = false;
    upBtn.onclick = () => loadInsFolderInModal(data.parent);
  } else {
    upBtn.disabled = true;
    upBtn.onclick = null;
  }

  if (!data.directories || data.directories.length === 0) {
    listEl.innerHTML = '<div class="status">No subfolders (you can still use this folder)</div>';
    return;
  }
  const paths = data.directories.map((d) => d.path);
  listEl.innerHTML = data.directories
    .map(
      (d, i) =>
        `<button type="button" class="modal-dir-item" data-idx="${i}">${esc(d.name)}/</button>`
    )
    .join("");
  listEl.querySelectorAll(".modal-dir-item").forEach((btn) => {
    btn.addEventListener("click", () => {
      const i = parseInt(btn.dataset.idx, 10);
      if (!Number.isNaN(i) && paths[i]) loadInsFolderInModal(paths[i]);
    });
  });
}

async function browseFiles() {
  const dir = $("#ins-dir").value.trim();
  if (!dir) return;

  const resp = await fetch(`/api/browse-audio?dir=${encodeURIComponent(dir)}`);
  const data = await resp.json();

  if (data.error) {
    $("#ins-file-list").innerHTML = `<div class="status">${data.error}</div>`;
    return;
  }

  $("#ins-dir").value = data.directory;
  if (typeof djmmSetLastAudioBrowseDir === "function") {
    djmmSetLastAudioBrowseDir(data.directory);
  }

  if (data.files.length === 0) {
    $("#ins-file-list").innerHTML = '<div class="status">No audio files found</div>';
    return;
  }

  $("#ins-file-list").innerHTML = data.files
    .map(
      (f) =>
        `<div class="file-item" data-path="${f.path}">
          <span class="file-name">${f.name}</span>
          <span class="file-size">${f.size_mb} MB</span>
        </div>`
    )
    .join("");

  $("#ins-file-list").querySelectorAll(".file-item").forEach((el) => {
    el.addEventListener("click", () => selectFile(el));
  });
}

async function selectFile(el) {
  $("#ins-file-list").querySelectorAll(".file-item").forEach((e) => e.classList.remove("selected"));
  el.classList.add("selected");
  selectedFile = el.dataset.path;

  $("#ins-details-layout").classList.remove("hidden");
  $("#ins-file-info").innerHTML = '<span class="spinner"></span> Reading file...';
  $("#ins-meta-table").innerHTML = "";
  $("#ins-art-info").innerHTML = "";
  $("#ins-art-preview").innerHTML = "";

  const resp = await fetch("/api/read-tags-full", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ filepath: selectedFile }),
  });
  const data = await resp.json();

  if (data.error) {
    $("#ins-file-info").innerHTML = `<div class="status">${data.error}</div>`;
    return;
  }

  renderFileInfo(data);
  renderMetadata(data);
  renderArtwork(data);
}

function renderFileInfo(data) {
  const fi = data.file_info || {};
  const rows = [
    ["File", fi.name || "—"],
    ["Path", fi.path || "—"],
    ["Size", fi.size_mb ? `${fi.size_mb} MB` : "—"],
    ["Format", data.format || fi.extension || "—"],
  ];

  $("#ins-file-info").innerHTML = rows
    .map(([k, v]) => `<div class="info-row"><span class="info-label">${k}</span><span class="info-value">${v}</span></div>`)
    .join("");
}

function renderMetadata(data) {
  const fields = [
    ["Title", data.title],
    ["Artist", data.artist],
    ["Album Artist", data.albumartist],
    ["Album", data.album],
    ["Year", data.date],
    ["Genre", data.genre],
    ["Track #", data.tracknumber],
    ["Label", data.label],
    ["Cat No.", data.catno],
    ["Comment", data.comment],
    ["Saved metadata URL", data.source_url],
  ];

  const hasAny = fields.some(([, v]) => v);

  if (!hasAny) {
    $("#ins-meta-table").innerHTML = '<div class="status inspect-empty">No metadata found in this file.</div>';
    return;
  }

  $("#ins-meta-table").innerHTML = fields
    .map(([label, value]) => {
      const cls = value ? "info-value" : "info-value info-missing";
      const display = value || "—";
      return `<div class="info-row"><span class="info-label">${label}</span><span class="${cls}">${display}</span></div>`;
    })
    .join("");
}

function renderArtwork(data) {
  const artInfo = $("#ins-art-info");
  const artPreview = $("#ins-art-preview");

  if (!data.has_artwork) {
    artInfo.innerHTML = '<div class="inspect-no-art">No artwork embedded in this file.</div>';
    artPreview.innerHTML = "";
    return;
  }

  const info = data.artwork_info || {};
  const rows = [];
  if (info.mime) rows.push(["Type", info.mime]);
  if (info.width && info.height) {
    rows.push(["Dimensions", `${info.width} × ${info.height}`]);
  } else {
    rows.push(["Dimensions", `<span class="info-missing">0 × 0 — missing dimensions</span>`]);
  }
  if (info.size_bytes) {
    const kb = (info.size_bytes / 1024).toFixed(1);
    rows.push(["Size", kb > 1024 ? `${(kb / 1024).toFixed(1)} MB` : `${kb} KB`]);
  }

  let fixBtn = "";
  if ((!info.width || !info.height) && data.file_info?.extension === ".flac") {
    fixBtn = `<div style="margin-top:0.75rem"><button id="fix-art-btn" class="btn btn-primary btn-sm">Fix Artwork Dimensions</button><span id="fix-art-status" class="settings-status hidden"></span></div>`;
  }

  artInfo.innerHTML = rows
    .map(([k, v]) => `<div class="info-row"><span class="info-label">${k}</span><span class="info-value">${v}</span></div>`)
    .join("") + fixBtn;

  const fixBtnEl = document.getElementById("fix-art-btn");
  if (fixBtnEl) {
    fixBtnEl.addEventListener("click", async () => {
      fixBtnEl.disabled = true;
      fixBtnEl.innerHTML = '<span class="spinner"></span> Fixing...';
      const r = await fetch("/api/fix-artwork", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ filepath: selectedFile }),
      });
      const result = await r.json();
      const statusEl = document.getElementById("fix-art-status");
      statusEl.classList.remove("hidden");
      if (result.error) {
        statusEl.textContent = result.error;
        statusEl.style.color = "var(--danger)";
      } else {
        statusEl.textContent = result.message;
        statusEl.style.color = "var(--success)";
        // Refresh the display
        const sel = $("#ins-file-list").querySelector(".file-item.selected");
        if (sel) setTimeout(() => selectFile(sel), 500);
      }
      fixBtnEl.disabled = false;
      fixBtnEl.textContent = "Fix Artwork Dimensions";
    });
  }

  const ts = Date.now();
  artPreview.innerHTML = `<img src="/api/embedded-artwork-img?path=${encodeURIComponent(selectedFile)}&t=${ts}" alt="Embedded artwork" onerror="this.parentElement.innerHTML='<span class=\\'status\\'>Failed to load artwork image</span>'" />`;
}

// ---- Event listeners ----
$("#ins-browse-btn").addEventListener("click", browseFiles);
document.getElementById("ins-choose-folder-btn").addEventListener("click", openInsFolderModal);
document.getElementById("ins-default-dir-btn").addEventListener("click", resetInspectDirToDefault);
document.getElementById("ins-modal-select").addEventListener("click", () => {
  if (insFolderModalPath) {
    $("#ins-dir").value = insFolderModalPath;
    closeInsFolderModal();
    browseFiles();
  }
});
document.getElementById("ins-modal-cancel").addEventListener("click", closeInsFolderModal);
document.getElementById("ins-folder-modal").addEventListener("click", (e) => {
  if (e.target && e.target.id === "ins-folder-modal") closeInsFolderModal();
});
$("#ins-dir").addEventListener("keydown", (e) => { if (e.key === "Enter") browseFiles(); });

// ---- Init ----
async function initInspect() {
  await loadSettings();
  const params = new URLSearchParams(window.location.search);
  const d = (params.get("dir") || "").trim();
  if (d) $("#ins-dir").value = d;
  await browseFiles();
}
initInspect();
