const $ = (sel) => document.querySelector(sel);

let selectedFile = null;
let currentTracklist = [];
let currentMeta = {};
let artworkUrl = "";

// ---- Browse FLACs ----
async function loadSettings() {
  const resp = await fetch("/api/settings");
  const cfg = await resp.json();
  $("#fix-dir").value = cfg.destination_dir || "";
}

async function browseFlacs() {
  const dir = $("#fix-dir").value.trim();
  if (!dir) return;

  const resp = await fetch(`/api/browse-flacs?dir=${encodeURIComponent(dir)}`);
  const data = await resp.json();

  if (data.error) {
    $("#fix-file-list").innerHTML = `<div class="status">${data.error}</div>`;
    return;
  }

  $("#fix-dir").value = data.directory;

  if (data.files.length === 0) {
    $("#fix-file-list").innerHTML = '<div class="status">No FLAC files found</div>';
    return;
  }

  $("#fix-file-list").innerHTML = data.files
    .map(
      (f) =>
        `<div class="file-item" data-path="${f.path}">
          <span class="file-name">${f.name}</span>
          <span class="file-size">${f.size_mb} MB</span>
        </div>`
    )
    .join("");

  $("#fix-file-list").querySelectorAll(".file-item").forEach((el) => {
    el.addEventListener("click", () => selectFlacFile(el));
  });
}

async function selectFlacFile(el) {
  $("#fix-file-list").querySelectorAll(".file-item").forEach((e) => e.classList.remove("selected"));
  el.classList.add("selected");
  selectedFile = el.dataset.path;
  currentTracklist = [];
  currentMeta = {};
  artworkUrl = "";

  $("#fix-save-btn").disabled = false;
  $("#fix-result").classList.add("hidden");
  $("#fix-tracklist-section").classList.add("hidden");

  const tags = $("#fix-current-tags");
  tags.classList.remove("hidden");
  tags.innerHTML = "Reading tags...";

  const resp = await fetch("/api/read-tags", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ filepath: selectedFile }),
  });
  const data = await resp.json();

  if (data.error) {
    tags.innerHTML = data.error;
    return;
  }

  const artStatus = data.has_artwork
    ? '<span style="color:var(--primary)">Has artwork</span>'
    : '<span style="color:var(--danger)">No artwork</span>';
  tags.innerHTML = `<span><strong>Current:</strong> ${data.title || "—"} — ${data.artist || "—"}</span><span>${artStatus}</span>`;

  $("#fix-title").value = data.title || "";
  $("#fix-artist").value = data.artist || "";
  $("#fix-albumartist").value = data.albumartist || "";
  $("#fix-album").value = data.album || "";
  $("#fix-date").value = data.date || "";
  $("#fix-genre").value = data.genre || "";
  $("#fix-label").value = data.label || "";
  $("#fix-catno").value = data.catno || "";
  $("#fix-comment").value = data.comment || "";

  $("#fix-artwork-preview").innerHTML = data.has_artwork
    ? '<span style="color:var(--primary)">Artwork embedded</span>'
    : "<span>No artwork</span>";
}

// ---- Fetch metadata ----
async function fetchMetadata() {
  const url = $("#fix-url").value.trim();
  const trackName = $("#fix-track-name").value.trim();
  const status = $("#fix-fetch-status");

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
  currentMeta = meta;
  status.classList.add("hidden");

  if (meta.tracklist && meta.tracklist.length > 1) {
    currentTracklist = meta.tracklist;
    showTracklist(meta);
    populateFromMeta(meta);
  } else {
    $("#fix-tracklist-section").classList.add("hidden");
    currentTracklist = [];
    populateFromMeta(meta);
  }

  if (meta._warning) {
    status.classList.remove("hidden");
    status.textContent = meta._warning;
  }
}

function populateFromMeta(meta) {
  if (meta.title) $("#fix-title").value = meta.title;
  if (meta.artist) $("#fix-artist").value = meta.artist;
  if (meta.albumartist) $("#fix-albumartist").value = meta.albumartist;
  if (meta.album) $("#fix-album").value = meta.album;
  if (meta.date) $("#fix-date").value = meta.date;
  if (meta.genre) $("#fix-genre").value = meta.genre;
  if (meta.label) $("#fix-label").value = meta.label;
  if (meta.catno) $("#fix-catno").value = meta.catno;

  if (meta.artwork_url) {
    artworkUrl = meta.artwork_url;
    const proxyUrl = `/api/fetch-artwork?url=${encodeURIComponent(artworkUrl)}`;
    $("#fix-artwork-preview").innerHTML = `<img src="${proxyUrl}" alt="Cover art" onerror="this.parentElement.innerHTML='<span>Failed to load</span>'" />`;
  }
}

// ---- Tracklist ----
function showTracklist(meta) {
  const section = $("#fix-tracklist-section");
  const container = $("#fix-tracklist");
  section.classList.remove("hidden");

  container.innerHTML = currentTracklist
    .map(
      (t, i) =>
        `<div class="track-item" data-index="${i}">
          <span class="track-pos">${t.position}</span>
          <span class="track-title">${t.title}${t.artist ? ` <span class="track-artist">— ${t.artist}</span>` : ""}</span>
          <span class="track-dur">${t.duration}</span>
        </div>`
    )
    .join("");

  container.querySelectorAll(".track-item").forEach((el) => {
    el.addEventListener("click", () => selectTrack(el, meta));
  });
}

function selectTrack(el, meta) {
  $("#fix-tracklist").querySelectorAll(".track-item").forEach((e) => e.classList.remove("selected"));
  el.classList.add("selected");

  const track = currentTracklist[parseInt(el.dataset.index)];
  $("#fix-title").value = track.title;
  $("#fix-artist").value = track.artist || meta.artist || "";
  if (meta.albumartist) $("#fix-albumartist").value = meta.albumartist;
  if (meta.album) $("#fix-album").value = meta.album;
  if (meta.date) $("#fix-date").value = meta.date;
  if (meta.genre) $("#fix-genre").value = meta.genre;
  if (meta.label) $("#fix-label").value = meta.label;
  if (meta.catno) $("#fix-catno").value = meta.catno;
  $("#fix-comment").value = `${track.position} - ${meta.album || ""}`.trim();
}

// ---- Clear all ----
function clearAll() {
  $("#fix-title").value = "";
  $("#fix-artist").value = "";
  $("#fix-albumartist").value = "";
  $("#fix-album").value = "";
  $("#fix-date").value = "";
  $("#fix-genre").value = "";
  $("#fix-label").value = "";
  $("#fix-catno").value = "";
  $("#fix-comment").value = "";
  $("#fix-url").value = "";
  $("#fix-track-name").value = "";
  $("#fix-artwork-preview").innerHTML = "<span>No artwork</span>";
  $("#fix-tracklist-section").classList.add("hidden");
  $("#fix-fetch-status").classList.add("hidden");
  $("#fix-result").classList.add("hidden");
  artworkUrl = "";
  currentTracklist = [];
  currentMeta = {};
}

// ---- Save tags ----
async function saveTags() {
  if (!selectedFile) return;

  const btn = $("#fix-save-btn");
  const result = $("#fix-result");
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Saving...';
  result.classList.add("hidden");

  const metadata = {
    title: $("#fix-title").value.trim(),
    artist: $("#fix-artist").value.trim(),
    albumartist: $("#fix-albumartist").value.trim(),
    album: $("#fix-album").value.trim(),
    date: $("#fix-date").value.trim(),
    genre: $("#fix-genre").value.trim(),
    comment: $("#fix-comment").value.trim(),
    label: $("#fix-label").value.trim(),
    catno: $("#fix-catno").value.trim(),
  };

  const resp = await fetch("/api/retag", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ filepath: selectedFile, metadata, artwork_url: artworkUrl }),
  });

  const data = await resp.json();
  result.classList.remove("hidden");

  if (data.error) {
    result.className = "result error";
    result.innerHTML = `<div class="result-title">Error</div><div class="result-detail">${data.error}</div>`;
  } else {
    result.className = "result";
    const filename = selectedFile.split("/").pop();
    const parts = [`Tags updated for <strong>${filename}</strong>`];
    if (artworkUrl) parts.push("Artwork embedded");
    result.innerHTML = `<div class="result-title">Saved!</div><div class="result-detail">${parts.join("<br>")}</div>`;

    const sel = $("#fix-file-list").querySelector(".file-item.selected");
    if (sel) selectFlacFile(sel);
  }

  btn.disabled = false;
  btn.textContent = "Save Tags & Artwork";
}

// ---- Event listeners ----
$("#fix-browse-btn").addEventListener("click", browseFlacs);
$("#fix-dir").addEventListener("keydown", (e) => { if (e.key === "Enter") browseFlacs(); });
$("#fix-fetch-btn").addEventListener("click", fetchMetadata);
$("#fix-url").addEventListener("keydown", (e) => { if (e.key === "Enter") fetchMetadata(); });
$("#fix-track-name").addEventListener("keydown", (e) => { if (e.key === "Enter") fetchMetadata(); });
$("#fix-clear-btn").addEventListener("click", clearAll);
$("#fix-save-btn").addEventListener("click", saveTags);

// ---- Init ----
loadSettings().then(() => browseFlacs());
