const $ = (sel) => document.querySelector(sel);

let selectedFile = null;
let currentTracklist = [];
let currentMeta = {};
let artworkUrl = "";
/** Paths in current file list (same order as .file-item data-idx). */
let fixBrowseFilePaths = [];

// ---- Filename helpers (e.g. Ableton: A06 - 139 - Artist - Title) ----
/** Match app.py `strip_rekordbox_style_filename_affixes` (trailing key+BPM, then lead slot). */
function stripRekordboxStyleFilenameAffixes(stem) {
  let t = (stem || "").trim();
  if (!t) return t;
  t = t.replace(/\s+\d{1,2}[AB]\s+\d{2,3}$/i, "").trim();
  t = t.replace(/^[A-Za-z]\d{1,2}\s+/i, "").trim();
  return t;
}

/**
 * If the stem looks like: [slot]-[BPM]-[artist]-[title], return a search string and
 * suggested title/artist for empty tags. Otherwise fall back to a looser string from the whole stem.
 * Rekordbox flat exports: "A02 Artist 2A 120" are normalized after the hyphenated form is ruled out.
 */
function parseAbletonStyleFilename(stem) {
  const t0 = (stem || "").replace(/_PN$/i, "").trim();
  if (!t0) {
    return { searchQuery: "", suggestedTitle: "", suggestedArtist: "" };
  }
  // E.g. A06 - 139 - Members Of Mayday - 10 In 01
  const m4 = t0.match(
    /^(?:[A-Za-z]?\d+|Track\s*\d+|\d+)\s*-\s*\d{2,3}\s*-\s*(.+?)\s*-\s*(.+)$/i
  );
  if (m4) {
    const artist = m4[1].trim();
    const title = m4[2].trim();
    return {
      searchQuery: [artist, title].join(" ").replace(/\s+/g, " ").trim(),
      suggestedTitle: title,
      suggestedArtist: artist,
    };
  }
  const t = stripRekordboxStyleFilenameAffixes(t0);
  if (!t) {
    return { searchQuery: "", suggestedTitle: "", suggestedArtist: "" };
  }
  const stripped = t.replace(/^(?:[A-Za-z]?\d+|Track\s*\d+|\d+)\s*-\s*\d{2,3}\s*-\s*/i, "").trim();
  const loose = (stripped || t).replace(/\s*-\s*/g, " ").replace(/_/g, " ").replace(/\s+/g, " ").trim();
  return { searchQuery: loose, suggestedTitle: "", suggestedArtist: "" };
}

// ---- Browse audio files ----
async function loadSettings() {
  const resp = await fetch("/api/settings");
  const cfg = await resp.json();
  const last = typeof djmmGetLastAudioBrowseDir === "function" ? djmmGetLastAudioBrowseDir().trim() : "";
  $("#fix-dir").value = last || cfg.destination_dir || "";
}

async function resetFixDirToDefault() {
  const resp = await fetch("/api/settings");
  const cfg = await resp.json();
  $("#fix-dir").value = cfg.destination_dir || "";
  await browseAudio();
}

// ---- Server-side folder picker (path cannot be read from a browser file dialog) ----
let folderModalPath = "";

function closeFolderModal() {
  const el = document.getElementById("fix-folder-modal");
  if (el) el.classList.add("hidden");
  document.removeEventListener("keydown", onFolderModalKeydown);
}

function onFolderModalKeydown(e) {
  if (e.key === "Escape") closeFolderModal();
}

async function openFolderModal() {
  let start = $("#fix-dir").value.trim();
  if (!start) {
    const resp = await fetch("/api/settings");
    const cfg = await resp.json();
    start = cfg.destination_dir || "";
  }
  if (!start) start = "~";
  const modal = document.getElementById("fix-folder-modal");
  modal.classList.remove("hidden");
  document.addEventListener("keydown", onFolderModalKeydown);
  await loadFolderInModal(start);
}

async function loadFolderInModal(path) {
  const listEl = $("#fix-modal-dir-list");
  const pathEl = $("#fix-modal-path");
  const upBtn = $("#fix-modal-up");
  listEl.innerHTML = '<div class="status">Loading…</div>';
  upBtn.disabled = true;

  const resp = await fetch(`/api/browse-folders?path=${encodeURIComponent(path)}`);
  const data = await resp.json();
  if (data.error) {
    listEl.innerHTML = `<div class="status">${data.error}</div>`;
    pathEl.textContent = path;
    folderModalPath = path;
    return;
  }
  folderModalPath = data.path;
  pathEl.textContent = data.path;
  if (data.parent) {
    upBtn.disabled = false;
    upBtn.onclick = () => loadFolderInModal(data.parent);
  } else {
    upBtn.disabled = true;
    upBtn.onclick = null;
  }

  if (!data.directories || data.directories.length === 0) {
    listEl.innerHTML = '<div class="status">No subfolders (you can still use this folder)</div>';
    return;
  }
  const paths = data.directories.map((d) => d.path);
  const esc = (s) =>
    String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  listEl.innerHTML = data.directories
    .map(
      (d, i) =>
        `<button type="button" class="modal-dir-item" data-idx="${i}">${esc(d.name)}/</button>`
    )
    .join("");
  listEl.querySelectorAll(".modal-dir-item").forEach((btn) => {
    btn.addEventListener("click", () => {
      const i = parseInt(btn.dataset.idx, 10);
      if (!Number.isNaN(i) && paths[i]) loadFolderInModal(paths[i]);
    });
  });
}

async function browseAudio() {
  const dir = $("#fix-dir").value.trim();
  if (!dir) {
    fixBrowseFilePaths = [];
    return null;
  }

  const resp = await fetch(`/api/browse-audio?dir=${encodeURIComponent(dir)}`);
  const data = await resp.json();

  if (data.error) {
    $("#fix-file-list").innerHTML = `<div class="status">${data.error}</div>`;
    fixBrowseFilePaths = [];
    return null;
  }

  $("#fix-dir").value = data.directory;
  if (typeof djmmSetLastAudioBrowseDir === "function") {
    djmmSetLastAudioBrowseDir(data.directory);
  }

  if (data.files.length === 0) {
    $("#fix-file-list").innerHTML = '<div class="status">No audio files found</div>';
    fixBrowseFilePaths = [];
    return data;
  }

  fixBrowseFilePaths = data.files.map((f) => f.path);
  const esc = (s) =>
    String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  $("#fix-file-list").innerHTML = data.files
    .map(
      (f, i) =>
        `<div class="file-item" data-idx="${i}">
          <span class="file-name">${esc(f.name)}</span>
          <span class="file-size">${f.size_mb} MB</span>
        </div>`
    )
    .join("");

  $("#fix-file-list").querySelectorAll(".file-item").forEach((el) => {
    el.addEventListener("click", () => selectFlacFile(el));
  });
  return data;
}

function findFileItemByPath(path) {
  const idx = fixBrowseFilePaths.indexOf(path);
  if (idx < 0) return null;
  return document.querySelector(`#fix-file-list .file-item[data-idx="${idx}"]`);
}

async function selectFlacFile(el) {
  $("#fix-file-list").querySelectorAll(".file-item").forEach((e) => e.classList.remove("selected"));
  el.classList.add("selected");
  const bidx = parseInt(el.dataset.idx, 10);
  selectedFile = !Number.isNaN(bidx) && fixBrowseFilePaths[bidx] ? fixBrowseFilePaths[bidx] : null;
  if (!selectedFile) return;
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
  const fmt = data.format ? `<span><strong>Format:</strong> ${data.format}</span>` : "";
  tags.innerHTML = `<span><strong>Current:</strong> ${data.title || "—"} — ${data.artist || "—"}</span>${fmt}<span>${artStatus}</span>`;

  $("#fix-title").value = data.title || "";
  $("#fix-artist").value = data.artist || "";
  $("#fix-albumartist").value = data.albumartist || "";
  $("#fix-album").value = data.album || "";
  $("#fix-date").value = data.date || "";
  $("#fix-genre").value = data.genre || "";
  $("#fix-label").value = data.label || "";
  $("#fix-catno").value = data.catno || "";
  $("#fix-comment").value = data.comment || "";
  $("#fix-url").value = data.source_url || "";

  const stem = selectedFile.split("/").pop().replace(/\.[^.]+$/, "");
  const parsed = parseAbletonStyleFilename(stem);
  if (!data.title && parsed.suggestedTitle) {
    $("#fix-title").value = parsed.suggestedTitle;
  }
  if (!data.artist && parsed.suggestedArtist) {
    $("#fix-artist").value = parsed.suggestedArtist;
  }

  let searchOverride = null;
  if (window.__fixSearchOverrideFromUrl) {
    searchOverride = window.__fixSearchOverrideFromUrl;
    window.__fixSearchOverrideFromUrl = null;
  } else if (!data.title && !data.artist) {
    searchOverride = parsed.searchQuery || null;
  }

  $("#fix-artwork-preview").innerHTML = data.has_artwork
    ? '<span style="color:var(--primary)">Artwork embedded</span>'
    : "<span>No artwork</span>";

  const searchPayload = { ...data };
  if (searchOverride) {
    searchPayload._searchQuery = searchOverride;
  }
  autoSearch(searchPayload);
  updateRenamePreview();
}

// ---- Auto-search from file tags ----
async function autoSearch(tags) {
  const section = $("#fix-search-section");
  const container = $("#fix-search-results");
  const status = $("#fix-search-status");

  const parts = [];
  let q;
  if (tags._searchQuery) {
    q = tags._searchQuery;
  } else {
    if (tags.title) parts.push(tags.title);
    if (tags.artist) parts.push(tags.artist);
    if (!parts.length) {
      const name = selectedFile
        ? selectedFile.split("/").pop().replace(/\.[^.]+$/, "").replace(/_PN$/, "")
        : "";
      const p = name ? parseAbletonStyleFilename(name) : { searchQuery: "" };
      if (p.searchQuery) {
        q = p.searchQuery;
      } else {
        const flat = name.replace(/[_-]/g, " ").replace(/\s+/g, " ").trim();
        if (flat) q = flat;
      }
    } else {
      q = parts.join(" ");
    }
  }

  if (!q) {
    section.classList.add("hidden");
    return;
  }

  section.classList.remove("hidden");
  status.classList.remove("hidden");
  status.innerHTML = '<span class="spinner"></span> Searching...';
  container.innerHTML = "";
  const resp = await fetch(`/api/search?q=${encodeURIComponent(q)}`);
  const data = await resp.json();

  status.classList.add("hidden");

  if (!data.results || data.results.length === 0) {
    container.innerHTML = '<div class="status">No results found. Try a URL below.</div>';
    return;
  }

  container.innerHTML = data.results
    .map((r, i) => {
      const srcMap = {
        discogs: { label: "Discogs", cls: "src-discogs" },
        apple_music: { label: "Apple Music", cls: "src-apple" },
        bandcamp: { label: "Bandcamp", cls: "src-bandcamp" },
      };
      const sm = srcMap[r.source] || { label: "Web", cls: "src-generic" };
      const srcClass = sm.cls;
      const srcLabel = sm.label;
      const thumb = r.artwork_thumb
        ? `<img class="search-thumb" src="${r.artwork_thumb}" alt="" />`
        : `<div class="search-thumb"></div>`;
      const detail = [r.artist, r.album, r.year].filter(Boolean).join(" · ");
      const label = r.label ? ` · ${r.label}` : "";
      return `<div class="search-item" data-index="${i}">
        ${thumb}
        <div class="search-info">
          <div class="search-title">${r.title}</div>
          <div class="search-detail">${detail}${label}</div>
        </div>
        <span class="search-source ${srcClass}">${srcLabel}</span>
      </div>`;
    })
    .join("");

  container.querySelectorAll(".search-item").forEach((el) => {
    el.addEventListener("click", () => pickSearchResult(el, data.results));
  });
}

async function pickSearchResult(el, results) {
  container = $("#fix-search-results");
  container.querySelectorAll(".search-item").forEach((e) => e.classList.remove("selected"));
  el.classList.add("selected");

  const r = results[parseInt(el.dataset.index)];
  if (!r.url) return;

  const status = $("#fix-fetch-status");
  status.classList.remove("hidden");
  status.innerHTML = '<span class="spinner"></span> Fetching full metadata...';

  const resp = await fetch("/api/fetch-metadata", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url: r.url }),
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

// ---- Fetch metadata from URL ----
async function fetchMetadata() {
  const url = $("#fix-url").value.trim();
  const status = $("#fix-fetch-status");

  if (!url) {
    status.classList.remove("hidden");
    status.textContent = "Enter a URL first.";
    return;
  }

  status.classList.remove("hidden");
  status.innerHTML = '<span class="spinner"></span> Fetching metadata...';

  const resp = await fetch("/api/fetch-metadata", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
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
  updateRenamePreview();
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
  updateRenamePreview();
}

// ---- Rename preview (match server: Artist - Title.ext) ----
function getExtensionForRename() {
  if (!selectedFile) return ".flac";
  const m = selectedFile.match(/(\.[^./]+)$/i);
  return m ? m[0].toLowerCase() : ".flac";
}

function previewRenamedFilename() {
  const artist = $("#fix-artist").value.trim();
  const title = $("#fix-title").value.trim();
  const ext = getExtensionForRename();
  if (!title && !artist) return null;
  let base = title && artist ? `${artist} - ${title}` : (title || artist);
  base = base.replace(/[<>:"/\\|?*]/g, "").replace(/\s+/g, " ").replace(/^\.+|\.+$/g, "").trim();
  if (!base) return null;
  if (base.length > 200) base = base.slice(0, 200).replace(/\s+$/, "");
  return `${base}${ext}`;
}

function updateRenamePreview() {
  const el = $("#fix-rename-preview");
  if (!$("#fix-rename-to-tags").checked) {
    el.textContent = "Rename is off — file on disk will keep the current name.";
    return;
  }
  const s = previewRenamedFilename();
  if (!s) {
    el.textContent = "Enter a title and/or artist to preview the new filename.";
    return;
  }
  el.textContent = `New filename: ${s}`;
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
  $("#fix-artwork-preview").innerHTML = "<span>No artwork</span>";
  $("#fix-tracklist-section").classList.add("hidden");
  $("#fix-search-section").classList.add("hidden");
  $("#fix-fetch-status").classList.add("hidden");
  $("#fix-result").classList.add("hidden");
  $("#fix-rename-to-tags").checked = false;
  updateRenamePreview();
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

  const metadata_source_url = $("#fix-url").value.trim();

  const resp = await fetch("/api/retag", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      filepath: selectedFile,
      metadata,
      artwork_url: artworkUrl,
      metadata_source_url,
      rename_to_tags: $("#fix-rename-to-tags").checked,
    }),
  });

  const data = await resp.json();
  result.classList.remove("hidden");

  if (data.error) {
    result.className = "result error";
    result.innerHTML = `<div class="result-title">Error</div><div class="result-detail">${data.error}</div>`;
  } else {
    result.className = "result";
    const outPath = data.filepath || selectedFile;
    const shortName = outPath.split("/").pop();
    const parts = [`Tags updated for <strong>${shortName}</strong>`];
    if (artworkUrl) parts.push("Artwork embedded");
    if (data.renamed) parts.push("File renamed on disk to match title &amp; artist.");
    result.innerHTML = `<div class="result-title">Saved!</div><div class="result-detail">${parts.join("<br>")}</div>`;

    if (outPath && (data.renamed || outPath !== selectedFile)) {
      const parent = outPath.split("/").slice(0, -1).join("/");
      if (parent) $("#fix-dir").value = parent;
      await browseAudio();
      const item = findFileItemByPath(outPath);
      if (item) {
        await selectFlacFile(item);
      } else {
        selectedFile = outPath;
      }
    } else {
      const sel = $("#fix-file-list").querySelector(".file-item.selected");
      if (sel) selectFlacFile(sel);
    }
  }

  btn.disabled = false;
  btn.textContent = "Save Tags & Artwork";
}

// ---- Event listeners ----
$("#fix-browse-btn").addEventListener("click", browseAudio);
document.getElementById("fix-choose-folder-btn").addEventListener("click", openFolderModal);
document.getElementById("fix-default-dir-btn").addEventListener("click", resetFixDirToDefault);
document.getElementById("fix-modal-select").addEventListener("click", () => {
  if (folderModalPath) {
    $("#fix-dir").value = folderModalPath;
    closeFolderModal();
    browseAudio();
  }
});
document.getElementById("fix-modal-cancel").addEventListener("click", closeFolderModal);
document.getElementById("fix-folder-modal").addEventListener("click", (e) => {
  if (e.target && e.target.id === "fix-folder-modal") closeFolderModal();
});
$("#fix-dir").addEventListener("keydown", (e) => { if (e.key === "Enter") browseAudio(); });
$("#fix-fetch-btn").addEventListener("click", fetchMetadata);
$("#fix-url").addEventListener("keydown", (e) => { if (e.key === "Enter") fetchMetadata(); });
$("#fix-clear-btn").addEventListener("click", clearAll);
$("#fix-save-btn").addEventListener("click", saveTags);
$("#fix-rename-to-tags").addEventListener("change", updateRenamePreview);
["fix-title", "fix-artist"].forEach((id) => {
  document.getElementById(id).addEventListener("input", updateRenamePreview);
});

// ---- Init (optional deep link: /fix?file=/path/to/song.flac &q=optional+search+query) ----
async function initFixPage() {
  const params = new URLSearchParams(window.location.search);
  const file = (params.get("file") || "").trim();
  const q = (params.get("q") || "").trim();
  if (q) {
    window.__fixSearchOverrideFromUrl = q;
  }
  await loadSettings();
  if (file) {
    const lastSlash = file.lastIndexOf("/");
    const dir = lastSlash > 0 ? file.slice(0, lastSlash) : "";
    if (dir) {
      $("#fix-dir").value = dir;
    }
    await browseAudio();
    const item = findFileItemByPath(file);
    if (item) {
      await selectFlacFile(item);
    } else {
      $("#fix-file-list").innerHTML =
        '<div class="status">That file is not in this folder listing. Set the path above, click <strong>Browse</strong>, then select the file. Or <a href="/fix">open Fix</a> without a link.</div>';
    }
    if (file || q) {
      try {
        history.replaceState({}, "", "/fix");
      } catch (e) {
        /* ignore */
      }
    }
  } else {
    await browseAudio();
  }
  updateRenamePreview();
}

initFixPage();
