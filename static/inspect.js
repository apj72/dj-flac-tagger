const $ = (sel) => document.querySelector(sel);

let selectedFile = null;

async function loadSettings() {
  const resp = await fetch("/api/settings");
  const cfg = await resp.json();
  $("#ins-dir").value = cfg.destination_dir || "";
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

  $("#ins-info-section").classList.remove("hidden");
  $("#ins-meta-section").classList.remove("hidden");
  $("#ins-art-section").classList.remove("hidden");
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
$("#ins-dir").addEventListener("keydown", (e) => { if (e.key === "Enter") browseFiles(); });

// ---- Init ----
loadSettings().then(() => browseFiles());
