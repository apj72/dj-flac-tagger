const $ = (sel) => document.querySelector(sel);

let selectedFile = null;
let currentTracklist = [];
let currentMeta = {};
let artworkUrl = "";
/** Paths in current file list (same order as .file-item data-idx). */
let fixBrowseFilePaths = [];
/** From Settings: suffixes to peel before search (same rules as server). */
let fixRetainSuffixPatterns = [];

function collectFixPageState() {
  const snap =
    currentMeta && typeof currentMeta === "object"
      ? { ...currentMeta }
      : {};
  delete snap.tracklist;
  return {
    v: 1,
    fixDir: $("#fix-dir").value,
    selectedFile,
    title: $("#fix-title").value,
    artist: $("#fix-artist").value,
    albumartist: $("#fix-albumartist").value,
    album: $("#fix-album").value,
    date: $("#fix-date").value,
    genre: $("#fix-genre").value,
    label: $("#fix-label").value,
    catno: $("#fix-catno").value,
    comment: $("#fix-comment").value,
    url: $("#fix-url").value,
    renameToTags: $("#fix-rename-to-tags").checked,
    artworkUrl,
    currentTracklist,
    currentMetaSnapshot: Object.keys(snap).length ? snap : null,
  };
}

function scheduleFixPageSave() {
  if (typeof djmmPageStateSchedule === "function") {
    djmmPageStateSchedule("fix", collectFixPageState);
  }
}

function applyFixFieldsOverlay(st) {
  if (st.title != null) $("#fix-title").value = st.title;
  if (st.artist != null) $("#fix-artist").value = st.artist;
  if (st.albumartist != null) $("#fix-albumartist").value = st.albumartist;
  if (st.album != null) $("#fix-album").value = st.album;
  if (st.date != null) $("#fix-date").value = st.date;
  if (st.genre != null) $("#fix-genre").value = st.genre;
  if (st.label != null) $("#fix-label").value = st.label;
  if (st.catno != null) $("#fix-catno").value = st.catno;
  if (st.comment != null) $("#fix-comment").value = st.comment;
  if (st.url != null) $("#fix-url").value = st.url;
  if (st.renameToTags != null) $("#fix-rename-to-tags").checked = st.renameToTags;
  if (st.artworkUrl != null) {
    artworkUrl = st.artworkUrl;
    if (artworkUrl) {
      const proxyUrl = `/api/fetch-artwork?url=${encodeURIComponent(artworkUrl)}`;
      $("#fix-artwork-preview").innerHTML = `<img src="${proxyUrl}" alt="Cover art" onerror="this.parentElement.innerHTML='<span>Failed to load</span>'" />`;
    }
  }
}

function wireFixPagePersistence() {
  const ids = [
    "fix-dir",
    "fix-title",
    "fix-artist",
    "fix-albumartist",
    "fix-album",
    "fix-date",
    "fix-genre",
    "fix-label",
    "fix-catno",
    "fix-comment",
    "fix-url",
  ];
  ids.forEach((id) => {
    document.getElementById(id)?.addEventListener("input", scheduleFixPageSave);
  });
  document.getElementById("fix-rename-to-tags")?.addEventListener("change", scheduleFixPageSave);
}

// ---- Filename helpers (Ableton export / performance sample names; Rekordbox uses tags+DB) ----
/** Match app.py `strip_rekordbox_style_filename_affixes` (trailing key+BPM, then lead slot). */
function stripRekordboxStyleFilenameAffixes(stem) {
  let t = (stem || "").trim();
  if (!t) return t;
  t = t.replace(/\s*-\s*\d{1,2}[AB]\s*-\s*\d{2,3}\s*$/i, "").trim();
  t = t.replace(/\s+\d{1,2}[AB]\s+\d{2,3}$/i, "").trim();
  t = t.replace(/^[A-Za-z]\d{1,2}\s+/i, "").trim();
  return t;
}

/**
 * Peel configured suffix patterns from the end of the stem (match app.py peel_fix_retain_suffixes).
 * Returns { core, retained } — retained is fragments after the core for re-attaching on rename.
 */
function peelFixRetainSuffixes(stem, lines) {
  let cur = (stem || "").trim();
  if (!cur || !lines || !lines.length) {
    return { core: cur, retained: "" };
  }
  const peeled = [];
  let safety = 0;
  while (cur && safety < 32) {
    safety += 1;
    let matchedPiece = null;
    for (const raw of lines) {
      if (raw == null) continue;
      const line = String(raw).trim();
      if (!line || line.startsWith("#")) continue;
      if (line.toLowerCase().startsWith("regex:")) {
        const pat = line.slice(6).trim();
        let rx;
        try {
          rx = new RegExp(pat);
        } catch (e) {
          continue;
        }
        const m = rx.exec(cur);
        if (m && m.index >= 0 && m.index + m[0].length === cur.length) {
          matchedPiece = m[0];
          break;
        }
      } else if (cur.endsWith(line)) {
        matchedPiece = line;
        break;
      }
    }
    if (!matchedPiece) break;
    peeled.push(matchedPiece);
    cur = cur.slice(0, cur.length - matchedPiece.length);
  }
  const retained = peeled.reverse().join("");
  return { core: cur, retained };
}

/**
 * Parse Ableton-style stems on a **core** stem (retain-suffixes already peeled).
 */
function parseAbletonStyleFilenameCore(stem) {
  let t0 = (stem || "").replace(/_PN$/i, "").trim();
  t0 = t0.replace(/_pn(?=\s*-)/gi, "").trim();
  if (!t0) {
    return { searchQuery: "", suggestedTitle: "", suggestedArtist: "" };
  }
  // E.g. A06 - 139 - Members Of Mayday - 10 In 01 (BPM in second field)
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
  // E.g. A01 - Artist - Title - 1A - 126 (leading key + trailing key + BPM; Ableton performance / browser)
  const mPerf = t0.match(/^(.+)\s*-\s*([0-9]{1,2}[ABab])\s*-\s*([0-9]{2,3})\s*$/i);
  if (mPerf) {
    const body = mPerf[1].trim();
    const mHead = body.match(/^([A-Za-z]?\d{1,2})\s*-\s*(.+)$/i);
    if (mHead) {
      const rest = mHead[2].trim();
      const sep = " - ";
      const i = rest.indexOf(sep);
      let artist;
      let title;
      if (i > 0) {
        artist = rest
          .slice(0, i)
          .trim()
          .replace(/[, ]+$/g, "")
          .replace(/,\s*$/g, "");
        title = rest.slice(i + sep.length).trim();
      } else {
        const m1 = rest.match(/^(.+?),\s*-\s*(.+)$/i);
        const m2 = m1 || rest.match(/^(.+?),\s+(.+)$/);
        if (m2) {
          artist = m2[1].trim().replace(/[, ]+$/g, "");
          title = m2[2].trim();
        }
      }
      if (artist && title) {
        return {
          searchQuery: [artist, title].join(" ").replace(/\s+/g, " ").trim(),
          suggestedTitle: title,
          suggestedArtist: artist,
        };
      }
    }
  }
  const t = stripRekordboxStyleFilenameAffixes(t0);
  if (!t) {
    return { searchQuery: "", suggestedTitle: "", suggestedArtist: "" };
  }
  const stripped = t.replace(/^(?:[A-Za-z]?\d+|Track\s*\d+|\d+)\s*-\s*\d{2,3}\s*-\s*/i, "").trim();
  const loose = (stripped || t).replace(/\s*-\s*/g, " ").replace(/_/g, " ").replace(/\s+/g, " ").trim();
  return { searchQuery: loose, suggestedTitle: "", suggestedArtist: "" };
}

/**
 * Parse Ableton-style stems; peels Settings “retain suffix” rules first so search ignores e.g. _warped.
 */
function parseAbletonStyleFilename(stem) {
  const peeled = peelFixRetainSuffixes(stem, fixRetainSuffixPatterns);
  const inner = parseAbletonStyleFilenameCore(peeled.core);
  return { ...inner, retainedSuffix: peeled.retained };
}

// ---- Browse audio files ----
function fixDefaultBrowseDir(cfg) {
  const d = ((cfg.fix_metadata_default_dir || "") + "").trim();
  if (d) return d;
  return ((cfg.destination_dir || "") + "").trim();
}

async function loadSettings() {
  const resp = await fetch("/api/settings");
  const cfg = await resp.json();
  const sfx = cfg.fix_retain_filename_suffixes;
  fixRetainSuffixPatterns = Array.isArray(sfx) ? sfx : [];
  const last = typeof djmmGetLastAudioBrowseDir === "function" ? djmmGetLastAudioBrowseDir().trim() : "";
  $("#fix-dir").value = last || fixDefaultBrowseDir(cfg);
}

async function resetFixDirToDefault() {
  const resp = await fetch("/api/settings");
  const cfg = await resp.json();
  $("#fix-dir").value = fixDefaultBrowseDir(cfg);
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
    start = fixDefaultBrowseDir(cfg);
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
    scheduleFixPageSave();
    return null;
  }

  $("#fix-dir").value = data.directory;
  if (typeof djmmSetLastAudioBrowseDir === "function") {
    djmmSetLastAudioBrowseDir(data.directory);
  }

  if (data.files.length === 0) {
    $("#fix-file-list").innerHTML = '<div class="status">No audio files found</div>';
    fixBrowseFilePaths = [];
    scheduleFixPageSave();
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
  scheduleFixPageSave();
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
    scheduleFixPageSave();
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
  window.__fixRetainedSuffixFromFile = parsed.retainedSuffix || "";
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
  scheduleFixPageSave();
}

function hideSearchFallback() {
  const fb = document.getElementById("fix-search-fallback");
  if (fb) fb.classList.add("hidden");
  const ms = document.getElementById("fix-search-manual-status");
  if (ms) {
    ms.classList.add("hidden");
    ms.textContent = "";
  }
}

function showSearchFallback(prefillQuery) {
  const fb = document.getElementById("fix-search-fallback");
  if (!fb) return;
  fb.classList.remove("hidden");
  const site = document.getElementById("fix-search-site");
  if (site) site.value = "apple_music";
  const inp = document.getElementById("fix-search-manual-q");
  if (inp && prefillQuery != null) inp.value = prefillQuery;
  const ms = document.getElementById("fix-search-manual-status");
  if (ms) {
    ms.classList.add("hidden");
    ms.textContent = "";
  }
}

function searchResultCardsHtml(results) {
  return results
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
}

function paintFixSearchResults(container, results) {
  if (!container) return;
  if (!results || results.length === 0) {
    container.innerHTML = "";
    return;
  }
  container.innerHTML = searchResultCardsHtml(results);
  container.querySelectorAll(".search-item").forEach((el) => {
    el.addEventListener("click", () => pickSearchResult(el, results));
  });
}

async function runFixManualSiteSearch() {
  const qEl = document.getElementById("fix-search-manual-q");
  const siteEl = document.getElementById("fix-search-site");
  const status = document.getElementById("fix-search-manual-status");
  const container = $("#fix-search-results");
  const q = (qEl && qEl.value.trim()) || "";
  const source = (siteEl && siteEl.value) || "apple_music";
  if (!q) {
    if (status) {
      status.classList.remove("hidden");
      status.textContent = "Enter a search query.";
    }
    return;
  }
  if (status) {
    status.classList.remove("hidden");
    status.innerHTML = '<span class="spinner"></span> Searching…';
  }
  const url = `/api/search?q=${encodeURIComponent(q)}&source=${encodeURIComponent(source)}&limit=3`;
  const resp = await fetch(url);
  const data = await resp.json();
  const top = (data.results || []).slice(0, 3);
  if (!top.length) {
    if (status) {
      status.classList.remove("hidden");
      status.textContent =
        "No results for this site. Try another catalogue or different words.";
    }
    if (container) container.innerHTML = "";
    return;
  }
  if (status) status.classList.add("hidden");
  paintFixSearchResults(container, top);
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
    hideSearchFallback();
    return;
  }

  section.classList.remove("hidden");
  hideSearchFallback();
  status.classList.remove("hidden");
  status.innerHTML = '<span class="spinner"></span> Searching...';
  container.innerHTML = "";
  const resp = await fetch(`/api/search?q=${encodeURIComponent(q)}`);
  const data = await resp.json();

  status.classList.add("hidden");

  if (!data.results || data.results.length === 0) {
    container.innerHTML =
      '<div class="status">No combined results from Apple Music, Discogs, or Bandcamp.</div>';
    showSearchFallback(q);
    return;
  }

  hideSearchFallback();
  paintFixSearchResults(container, data.results);
}

async function pickSearchResult(el, results) {
  const container = $("#fix-search-results");
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
  scheduleFixPageSave();
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
  scheduleFixPageSave();
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
  scheduleFixPageSave();
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
  scheduleFixPageSave();
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
  const sfx =
    typeof window.__fixRetainedSuffixFromFile === "string" ? window.__fixRetainedSuffixFromFile : "";
  return `${base}${sfx}${ext}`;
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
  hideSearchFallback();
  $("#fix-fetch-status").classList.add("hidden");
  $("#fix-result").classList.add("hidden");
  $("#fix-rename-to-tags").checked = false;
  window.__fixRetainedSuffixFromFile = "";
  updateRenamePreview();
  artworkUrl = "";
  currentTracklist = [];
  currentMeta = {};
  scheduleFixPageSave();
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
  scheduleFixPageSave();
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
document.getElementById("fix-search-manual-btn")?.addEventListener("click", runFixManualSiteSearch);
document.getElementById("fix-search-manual-q")?.addEventListener("keydown", (e) => {
  if (e.key === "Enter") runFixManualSiteSearch();
});
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
  const st = !file && typeof djmmPageStateGetPage === "function" ? djmmPageStateGetPage("fix") : null;

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
    if (st && st.v === 1 && st.fixDir != null) $("#fix-dir").value = st.fixDir;
    await browseAudio();
    if (st && st.v === 1 && st.selectedFile) {
      const item = findFileItemByPath(st.selectedFile);
      if (item) await selectFlacFile(item);
    }
    if (st && st.v === 1) {
      applyFixFieldsOverlay(st);
      if (st.currentTracklist && st.currentTracklist.length > 1 && st.currentMetaSnapshot) {
        currentTracklist = st.currentTracklist;
        currentMeta = { ...st.currentMetaSnapshot };
        showTracklist(currentMeta);
      }
    }
  }
  updateRenamePreview();
  wireFixPagePersistence();
  scheduleFixPageSave();
}

initFixPage();
