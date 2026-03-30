const $ = (sel) => document.querySelector(sel);

let selectedFile = null;
let currentTracklist = [];

// ---- Settings ----
async function loadSettings() {
  const resp = await fetch("/api/settings");
  const cfg = await resp.json();
  $("#cfg-source").value = cfg.source_dir || "";
  $("#cfg-dest").value = cfg.destination_dir || "";
  $("#dir-input").value = cfg.source_dir_resolved || "";
}

async function saveSettings() {
  const resp = await fetch("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      source_dir: $("#cfg-source").value.trim(),
      destination_dir: $("#cfg-dest").value.trim(),
    }),
  });
  const cfg = await resp.json();
  $("#dir-input").value = cfg.source_dir_resolved || "";

  const status = $("#settings-status");
  status.classList.remove("hidden");
  setTimeout(() => status.classList.add("hidden"), 2000);

  browseFiles();
}

function toggleSettings() {
  const body = $("#settings-body");
  const arrow = $("#toggle-arrow");
  body.classList.toggle("hidden");
  arrow.classList.toggle("open");
}

// ---- Browse files ----
async function browseFiles() {
  const dir = $("#dir-input").value.trim() || "";
  const params = dir ? `?dir=${encodeURIComponent(dir)}` : "";
  const resp = await fetch(`/api/browse${params}`);
  const data = await resp.json();

  if (data.error) {
    $("#file-list").innerHTML = `<div class="status">${data.error}</div>`;
    return;
  }

  $("#dir-input").value = data.directory;

  if (data.files.length === 0) {
    $("#file-list").innerHTML = `<div class="status">No video files found</div>`;
    return;
  }

  $("#file-list").innerHTML = data.files
    .map(
      (f) =>
        `<div class="file-item" data-path="${f.path}">
          <span class="file-name">${f.name}</span>
          <span class="file-size">${f.size_mb} MB</span>
        </div>`
    )
    .join("");

  document.querySelectorAll(".file-item").forEach((el) => {
    el.addEventListener("click", () => selectFile(el));
  });
}

async function selectFile(el) {
  document.querySelectorAll(".file-item").forEach((e) => e.classList.remove("selected"));
  el.classList.add("selected");
  selectedFile = el.dataset.path;
  updateExtractButton();

  const probe = $("#probe-info");
  probe.classList.remove("hidden");
  probe.innerHTML = "Analyzing...";

  const resp = await fetch("/api/probe", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ filepath: selectedFile }),
  });
  const data = await resp.json();

  if (data.error) {
    probe.innerHTML = data.error;
    return;
  }

  const dur = data.duration ? formatDuration(parseFloat(data.duration)) : "?";
  probe.innerHTML = `
    <span><strong>Audio:</strong> ${(data.codec || "?").toUpperCase()}</span>
    <span><strong>Rate:</strong> ${data.sample_rate || "?"} Hz</span>
    <span><strong>Channels:</strong> ${data.channels || "?"}</span>
    <span><strong>Duration:</strong> ${dur}</span>
  `;
}

function formatDuration(secs) {
  const m = Math.floor(secs / 60);
  const s = Math.floor(secs % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

// ---- Clear / Populate metadata fields ----
function clearAllFields() {
  $("#meta-title").value = "";
  $("#meta-artist").value = "";
  $("#meta-albumartist").value = "";
  $("#meta-album").value = "";
  $("#meta-date").value = "";
  $("#meta-genre").value = "";
  $("#meta-comment").value = "";
  $("#meta-label").value = "";
  $("#meta-catno").value = "";
  $("#artwork-url").value = "";
  $("#artwork-preview").innerHTML = "<span>No artwork</span>";
  $("#track-url").value = "";
  $("#track-name").value = "";
  $("#tracklist-section").classList.add("hidden");
  $("#fetch-status").classList.add("hidden");
  $("#result").classList.add("hidden");
  currentTracklist = [];
}

function populateFields(meta) {
  clearAllFields();

  if (meta.title) $("#meta-title").value = meta.title;
  if (meta.artist) $("#meta-artist").value = meta.artist;
  if (meta.albumartist) $("#meta-albumartist").value = meta.albumartist;
  if (meta.album) $("#meta-album").value = meta.album;
  if (meta.date) $("#meta-date").value = meta.date;
  if (meta.genre) $("#meta-genre").value = meta.genre;
  if (meta.comment) $("#meta-comment").value = meta.comment;
  if (meta.label) $("#meta-label").value = meta.label;
  if (meta.catno) $("#meta-catno").value = meta.catno;

  if (meta.artwork_url) {
    $("#artwork-url").value = meta.artwork_url;
    loadArtworkPreview(meta.artwork_url);
  }

  updateExtractButton();
}

// ---- Tracklist ----
function showTracklist(tracklist, meta) {
  currentTracklist = tracklist;
  const section = $("#tracklist-section");
  const container = $("#tracklist");

  if (!tracklist || tracklist.length <= 1) {
    section.classList.add("hidden");
    return;
  }

  section.classList.remove("hidden");
  container.innerHTML = tracklist
    .map(
      (t, i) =>
        `<div class="track-item" data-index="${i}">
          <span class="track-pos">${t.position}</span>
          <span class="track-title">${t.title}</span>
          <span class="track-dur">${t.duration}</span>
        </div>`
    )
    .join("");

  container.querySelectorAll(".track-item").forEach((el) => {
    el.addEventListener("click", () => selectTrack(el, meta));
  });
}

function selectTrack(el, meta) {
  document.querySelectorAll(".track-item").forEach((e) => e.classList.remove("selected"));
  el.classList.add("selected");

  const idx = parseInt(el.dataset.index);
  const track = currentTracklist[idx];

  $("#meta-title").value = track.title;
  $("#meta-artist").value = meta.artist || "";
  if (meta.albumartist) $("#meta-albumartist").value = meta.albumartist;
  if (meta.album) $("#meta-album").value = meta.album;
  if (meta.date) $("#meta-date").value = meta.date;
  if (meta.genre) $("#meta-genre").value = meta.genre;
  if (meta.label) $("#meta-label").value = meta.label;
  if (meta.catno) $("#meta-catno").value = meta.catno;

  $("#meta-comment").value = `${track.position} - ${meta.album || ""}`.trim();

  updateExtractButton();
}

// ---- Fetch metadata ----
async function fetchMetadata() {
  const url = $("#track-url").value.trim();
  const trackName = $("#track-name").value.trim();
  const status = $("#fetch-status");

  if (!url && !trackName) {
    status.classList.remove("hidden");
    status.textContent = "Enter a URL or track name first.";
    return;
  }

  status.classList.remove("hidden");
  status.innerHTML = '<span class="spinner"></span> Fetching metadata...';

  const resp = await fetch("/api/fetch-metadata", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url, track_name: trackName }),
  });

  const meta = await resp.json();
  status.classList.add("hidden");

  populateFields(meta);

  if (meta.tracklist && meta.tracklist.length > 1) {
    showTracklist(meta.tracklist, meta);
  } else {
    $("#tracklist-section").classList.add("hidden");
  }

  if (meta._warning) {
    status.classList.remove("hidden");
    status.textContent = meta._warning;
  }
}

// ---- Artwork preview ----
function loadArtworkPreview(url) {
  if (!url) return;
  const container = $("#artwork-preview");
  const proxyUrl = `/api/fetch-artwork?url=${encodeURIComponent(url)}`;
  container.innerHTML = `<img src="${proxyUrl}" alt="Cover art" onerror="this.parentElement.innerHTML='<span>Failed to load</span>'" />`;
}

// ---- Extract ----
async function extractAndTag() {
  if (!selectedFile) return;

  const btn = $("#extract-btn");
  const result = $("#result");
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Extracting...';
  result.classList.add("hidden");

  const metadata = {
    title: $("#meta-title").value.trim(),
    artist: $("#meta-artist").value.trim(),
    albumartist: $("#meta-albumartist").value.trim(),
    album: $("#meta-album").value.trim(),
    date: $("#meta-date").value.trim(),
    genre: $("#meta-genre").value.trim(),
    comment: $("#meta-comment").value.trim(),
    label: $("#meta-label").value.trim(),
    catno: $("#meta-catno").value.trim(),
  };

  const artworkUrl = $("#artwork-url").value.trim();
  const deleteSource = $("#delete-source").checked;

  const resp = await fetch("/api/extract", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      filepath: selectedFile,
      metadata,
      artwork_url: artworkUrl,
      delete_source: deleteSource,
    }),
  });

  const data = await resp.json();
  result.classList.remove("hidden");

  if (data.error) {
    result.className = "result error";
    result.innerHTML = `
      <div class="result-title">Error</div>
      <div class="result-detail">${data.error}</div>
    `;
  } else {
    result.className = "result";
    const lines = [
      `<strong>${data.title}.flac</strong> (${data.size_mb} MB)`,
      `Source codec: ${data.source_codec.toUpperCase()} &rarr; FLAC (lossless)`,
      `Saved to: ${data.output_path}`,
    ];
    if (data.copied_to) lines.push(`Copied to: ${data.copied_to}`);
    if (data.copy_error) lines.push(`Copy failed: ${data.copy_error}`);
    if (data.source_trashed) lines.push(`Source MKV moved to Bin`);
    if (data.source_trash_error) lines.push(`Could not trash source: ${data.source_trash_error}`);

    result.innerHTML = `
      <div class="result-title">Done!</div>
      <div class="result-detail">${lines.join("<br>")}</div>
    `;
    if (data.source_trashed) {
      browseFiles();
    }
  }

  btn.disabled = false;
  btn.textContent = "Extract FLAC & Apply Tags";
}

function updateExtractButton() {
  $("#extract-btn").disabled = !selectedFile;
}

// ---- Event listeners ----
$("#settings-toggle").addEventListener("click", toggleSettings);
$("#save-settings-btn").addEventListener("click", saveSettings);

$("#browse-btn").addEventListener("click", browseFiles);
$("#dir-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter") browseFiles();
});

$("#fetch-btn").addEventListener("click", fetchMetadata);
$("#track-url").addEventListener("keydown", (e) => {
  if (e.key === "Enter") fetchMetadata();
});
$("#track-name").addEventListener("keydown", (e) => {
  if (e.key === "Enter") fetchMetadata();
});

$("#preview-art-btn").addEventListener("click", () => {
  loadArtworkPreview($("#artwork-url").value.trim());
});

$("#extract-btn").addEventListener("click", extractAndTag);
$("#clear-btn").addEventListener("click", clearAllFields);

// ---- Init ----
loadSettings().then(() => browseFiles());
