const $ = (sel) => document.querySelector(sel);

let fixListAll = [];
let selectedIdx = -1;
let completedPaths = [];
let exportedPaths = new Set();

// Background queue state
let queueRunning = false;
let queueAbort = false;
let currentlyFetchingIdx = -1;
let priorityIdx = -1;
let artworkFetchGen = 0;

const BATCH_SIZE = 25;
const BATCH_RESUME_PCT = 0.75;

function esc(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function flShowConfirm(title, bodyHtml, okText) {
  return new Promise((resolve) => {
    const modal = document.getElementById("fl-confirm-modal");
    const okBtn = document.getElementById("fl-confirm-ok");
    const cancelBtn = document.getElementById("fl-confirm-cancel");
    const titleEl = document.getElementById("fl-confirm-title");
    const bodyEl = document.getElementById("fl-confirm-body");
    if (!modal || !okBtn || !cancelBtn || !titleEl || !bodyEl) { resolve(false); return; }
    titleEl.textContent = title;
    bodyEl.innerHTML = bodyHtml;
    okBtn.textContent = okText;
    let done = false;
    function finish(val) {
      if (done) return;
      done = true;
      modal.classList.add("hidden");
      okBtn.removeEventListener("click", onOk);
      cancelBtn.removeEventListener("click", onCancel);
      document.removeEventListener("keydown", onDocKey);
      modal.removeEventListener("click", onOverlay);
      resolve(val);
    }
    function onOk() { finish(true); }
    function onCancel() { finish(false); }
    function onDocKey(e) { if (e.key === "Escape") onCancel(); }
    function onOverlay(e) { if (e.target === modal) onCancel(); }
    okBtn.addEventListener("click", onOk);
    cancelBtn.addEventListener("click", onCancel);
    document.addEventListener("keydown", onDocKey);
    modal.addEventListener("click", onOverlay);
    modal.classList.remove("hidden");
    requestAnimationFrame(() => okBtn.focus());
  });
}

function setProgress(visible, label) {
  const wrap = document.getElementById("fl-progress-wrap");
  const lab = document.getElementById("fl-progress-label");
  if (!wrap) return;
  wrap.classList.toggle("hidden", !visible);
  if (lab && label) lab.textContent = label;
}

function setStatus(text, isError) {
  const el = $("#fl-upload-status");
  if (!el) return;
  el.textContent = text;
  el.classList.toggle("hidden", !text);
  el.classList.toggle("error", !!isError);
}

function showSummary(summary) {
  const wrap = $("#fl-summary");
  const content = $("#fl-summary-content");
  if (!wrap || !content) return;
  wrap.classList.remove("hidden");
  const parts = [
    `<strong>${summary.total}</strong> track(s) in CSV`,
    `<strong>${summary.files_found}</strong> found on disk`,
  ];
  if (summary.files_missing > 0) {
    parts.push(`<span style="color:var(--danger)"><strong>${summary.files_missing}</strong> file(s) not found</span>`);
  }
  if (summary.needs_tags > 0) parts.push(`<strong>${summary.needs_tags}</strong> missing title/artist`);
  if (summary.needs_artwork > 0) parts.push(`<strong>${summary.needs_artwork}</strong> missing artwork`);
  content.innerHTML = parts.join(" &middot; ");
}

// ── Scoring (same logic as bulk-fix) ──

function normTokens(s) {
  return new Set(
    String(s || "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim()
      .split(/\s+/).filter((w) => w.length > 1),
  );
}
function tokenOverlap(a, b) {
  if (!a.size || !b.size) return 0;
  let n = 0;
  for (const t of a) { if (b.has(t)) n += 1; }
  return n;
}
function compactAlnum(s) {
  return String(s || "").toLowerCase().replace(/[^a-z0-9]+/g, "");
}

function scoreResult(item, r, index, nResults) {
  const url = (r.url || "").trim();
  if (!url) return -1e9;
  const titleT = normTokens(r.title);
  const artistT = normTokens(r.artist || "");
  const albumT = normTokens(r.album || "");
  const cand = new Set([...titleT, ...artistT, ...albumT]);
  const hintTitle = normTokens(item.title_hint);
  const hintArtist = normTokens(item.artist_hint);
  const hintQuery = normTokens(item.query);
  let score = 0;
  score += tokenOverlap(hintTitle, titleT) * 5;
  score += tokenOverlap(hintArtist, artistT) * 5;
  score += tokenOverlap(hintTitle, cand) * 2;
  score += tokenOverlap(hintArtist, cand) * 2;
  score += tokenOverlap(hintQuery, cand) * 1.2;
  const thc = compactAlnum(item.title_hint);
  const tac = compactAlnum([r.title, r.artist, r.album].filter(Boolean).join(" "));
  if (thc.length >= 4 && tac.includes(thc)) score += 6;
  const ahc = compactAlnum(item.artist_hint);
  if (ahc.length >= 4 && tac.includes(ahc)) score += 4;
  const src = String(r.source || "").toLowerCase();
  if (src === "apple_music" || src === "itunes") score += 1.2;
  else if (src === "discogs") score += 1;
  else if (src === "soundcloud") score += 0.85;
  else if (src === "bandcamp") score += 0.6;
  score += (nResults - index) * 0.04;
  return score;
}

function pickBestMatch(item) {
  const results = item.results || [];
  let bestUrl = "";
  let bestScore = -1e9;
  results.forEach((r, i) => {
    const sc = scoreResult(item, r, i, results.length);
    if (sc > bestScore) { bestScore = sc; bestUrl = (r.url || "").trim(); }
  });
  return bestUrl;
}

function formatBadgeHtml(fileType) {
  const ft = (fileType || "").toUpperCase();
  const cls = ft === "FLAC" ? "format-badge format-badge--flac"
    : ft === "MP3" ? "format-badge format-badge--mp3"
    : ft === "M4A" || ft === "AAC" ? "format-badge format-badge--m4a"
    : ft === "AIFF" || ft === "AIF" ? "format-badge format-badge--aiff"
    : "format-badge";
  return `<span class="${cls}">${esc(ft || "?")}</span>`;
}

function missingBadgesHtml(item) {
  const badges = [];
  const csvM = item.csv_missing || {};
  const tags = item.actual_tags || {};
  if (csvM.title || !(tags.title || "").trim()) badges.push('<span class="missing-badge" title="Missing title">T</span>');
  if (csvM.artist || !(tags.artist || "").trim()) badges.push('<span class="missing-badge" title="Missing artist">A</span>');
  if (csvM.bpm) badges.push('<span class="missing-badge missing-badge--warn" title="Missing BPM">B</span>');
  if (csvM.key) badges.push('<span class="missing-badge missing-badge--warn" title="Missing key">K</span>');
  if (!tags.has_artwork) badges.push('<span class="missing-badge" title="Missing artwork">W</span>');
  return badges.join("");
}

// ── State persistence ──

function saveState() {
  const payload = { v: 4, fixListAll, completedPaths, selectedIdx, exportedPaths: [...exportedPaths] };
  fetch("/api/fix-list/state", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  }).catch(() => {});
}

function scheduleSave() {
  clearTimeout(scheduleSave._t);
  scheduleSave._t = setTimeout(saveState, 400);
}

// ── Queue status display ──

function updateQueueStatus() {
  const el = $("#fl-list-count");
  if (!el) return;
  const total = fixListAll.filter((it) => it.file_exists && it.query).length;
  const fetched = fixListAll.filter((it) => it.fetched).length;
  const done = completedPaths.length;
  let text = `${fixListAll.length} tracks`;
  if (done) text += ` · ${done} fixed`;
  if (queueRunning && fetched < total) {
    text += ` · searching ${fetched}/${total}`;
  } else if (fetched > 0 && fetched >= total) {
    text += ` · all searched`;
  } else if (!queueRunning && fetched > 0 && fetched < total && batchLimitReached()) {
    text += ` · paused (fix more tracks to continue)`;
  }
  el.textContent = text;
}

// ── Track list rendering ──

function renderTrackList() {
  const list = $("#fl-track-list");
  if (!fixListAll.length) {
    list.innerHTML = '<p class="hint" style="padding:0.5rem">No tracks loaded.</p>';
    updateQueueStatus();
    return;
  }

  const scrollTop = list.scrollTop;

  list.innerHTML = fixListAll.map((item, idx) => {
    const name = item.file_name || item.full_path.split("/").pop();
    const isDone = completedPaths.includes(item.full_path);
    const isMissing = !item.file_exists;
    const isFetching = idx === currentlyFetchingIdx;
    const sel = idx === selectedIdx ? " selected" : "";
    const doneClass = isDone ? " fl-done" : "";
    const missingClass = isMissing ? " fl-missing-file" : "";
    const fetchingClass = isFetching ? " fl-fetching" : "";

    let statusIcon = "";
    if (isDone) {
      statusIcon = '<span class="fl-track-done-tick" title="Applied">&#10003;</span>';
    } else if (isFetching) {
      statusIcon = '<span class="fl-track-spinner" title="Searching…"></span>';
    } else if (item.fetched && (item.results || []).length > 0) {
      statusIcon = '<span class="fl-track-ready" title="Matches found">&#9679;</span>';
    }

    return `<div class="fl-track-item${sel}${doneClass}${missingClass}${fetchingClass}" role="option" aria-selected="${idx === selectedIdx}" data-idx="${idx}">
      ${statusIcon}
      <span class="fl-track-name" title="${esc(name)}">${esc(name)}</span>
      <span class="fl-track-badges">${formatBadgeHtml(item.file_type)}${missingBadgesHtml(item)}</span>
    </div>`;
  }).join("");

  list.scrollTop = scrollTop;

  list.querySelectorAll(".fl-track-item").forEach((el) => {
    el.addEventListener("click", () => {
      const idx = parseInt(el.dataset.idx, 10);
      if (Number.isNaN(idx)) return;
      const item = fixListAll[idx];
      if (!item || !item.file_exists) return;
      selectTrack(idx);
    });
  });

  updateQueueStatus();
}

function selectTrack(idx) {
  selectedIdx = idx;
  renderTrackList();
  renderDetail();
  scheduleSave();
  const item = fixListAll[idx];
  if (item && item.file_exists && window.DJMM?.setPlayerTrack) {
    window.DJMM.setPlayerTrack(item.full_path, item.file_name);
  }
}

// ── Detail panel ──

function renderDetail() {
  const panel = $("#fl-detail");
  if (selectedIdx < 0 || !fixListAll[selectedIdx]) {
    panel.innerHTML = '<div class="fl-detail-empty"><p class="hint">Select a track from the list to see its details.</p></div>';
    return;
  }
  const item = fixListAll[selectedIdx];
  const tags = item.actual_tags || {};
  const isDone = completedPaths.includes(item.full_path);
  const isFetching = selectedIdx === currentlyFetchingIdx;
  const isPending = !item.fetched && !isFetching;

  const edit = item.editMeta || {};

  const selectedUrl = (item.selectedUrl || "").trim();
  const results = item.results || [];

  let resultListHtml;
  if (isFetching) {
    resultListHtml = '<div class="fl-searching-msg"><span class="fl-track-spinner"></span> Searching online sources… results will appear shortly.</div>';
  } else if (isPending && queueRunning) {
    const pos = fixListAll.filter((it, i) => i < selectedIdx && it.file_exists && it.query && !it.fetched).length;
    resultListHtml = `<div class="fl-pending-msg">Queued for search (${pos > 0 ? pos + " track(s) ahead" : "up next"}). Click "Fetch now" to search immediately.</div>`;
  } else if (results.length) {
    resultListHtml = results.map((r, ri) => {
      const u = (r.url || "").trim();
      const isSelected = selectedUrl && u === selectedUrl;
      const srcMap = {
        discogs: { label: "Discogs", cls: "src-discogs" },
        apple_music: { label: "Apple Music", cls: "src-apple" },
        bandcamp: { label: "Bandcamp", cls: "src-bandcamp" },
        soundcloud: { label: "SoundCloud", cls: "src-soundcloud" },
        beatport: { label: "Beatport", cls: "src-beatport" },
      };
      const sm = srcMap[r.source] || { label: "Web", cls: "src-generic" };
      const thumbUrl = r.artwork_thumb || r.artwork_url || "";
      const thumb = thumbUrl
        ? `<img class="search-thumb search-thumb--has-art" src="${esc(thumbUrl)}" alt="" title="Click for artwork only" />`
        : `<div class="search-thumb"></div>`;
      const detail = [r.artist, r.album, r.year].filter(Boolean).join(" · ");
      const labelText = r.label ? ` · ${r.label}` : "";
      return `<div class="search-item${isSelected ? " selected" : ""}" data-ridx="${ri}">
        ${thumb}
        <div class="search-info">
          <div class="search-title">${esc(r.title || "")}</div>
          <div class="search-detail">${esc(detail + labelText)}</div>
        </div>
        <span class="search-source ${sm.cls}">${sm.label}</span>
      </div>`;
    }).join("");
  } else if (item.fetchError) {
    resultListHtml = `<p class="hint" style="color:var(--danger)">${esc(item.fetchError)}</p>`;
  } else if (item.fetched) {
    resultListHtml = '<p class="hint">No matches found. Try a different query or paste a URL below.</p>';
  } else {
    resultListHtml = '<p class="hint">Click "Fetch now" to search for this track.</p>';
  }

  const prevDisabled = selectedIdx <= 0 ? " disabled" : "";
  const nextIdx = findNextTrack(selectedIdx);
  const nextDisabled = nextIdx < 0 ? " disabled" : "";
  const fetchBtnLabel = isFetching ? "Searching…" : (item.fetched ? "Re-fetch" : "Fetch now");
  const fetchBtnDisabled = isFetching ? " disabled" : "";

  const artUrl = edit.artwork_url || "";
  const artPreview = artUrl
    ? `<img src="${esc(artUrl)}" alt="Artwork preview" style="width:100%;height:100%;object-fit:cover;border-radius:var(--radius-sm)" />`
    : `<span>${tags.has_artwork ? "File has artwork" : "No artwork"}</span>`;

  const hasEdits = !!(edit.title || edit.artist || edit.album || edit.artwork_url);

  panel.innerHTML = `<div class="fl-detail-content">
    <div class="fl-detail-header">
      <p class="fl-detail-filename">${esc(item.file_name)}</p>
      <div class="fl-detail-badges">
        ${formatBadgeHtml(item.file_type)}
        ${missingBadgesHtml(item)}
        ${isDone ? '<span style="color:var(--success);font-weight:600;font-size:0.85rem">&#10003; Applied</span>' : ""}
      </div>
    </div>

    <div class="fl-detail-search">
      <div class="fl-detail-search-row">
        <div style="flex:1 1 auto">
          <label for="fl-query" style="display:block;font-size:0.8rem;margin-bottom:0.2rem">Search query</label>
          <input type="text" id="fl-query" value="${esc(item.query)}" />
        </div>
        <button type="button" id="fl-fetch-one-btn" class="btn btn-primary"${fetchBtnDisabled}>${fetchBtnLabel}</button>
      </div>
      <div class="fl-detail-results" id="fl-detail-results">
        ${resultListHtml}
      </div>
    </div>

    <div class="fl-detail-manual">
      <div class="fl-detail-search-row">
        <div style="flex:1 1 auto">
          <label for="fl-manual-url" style="display:block;font-size:0.8rem;margin-bottom:0.2rem">Or paste a URL (Discogs, Bandcamp, Apple Music, SoundCloud, Beatport)</label>
          <input type="url" id="fl-manual-url" placeholder="https://…" value="${esc(item.manualUrl || "")}" />
        </div>
        <button type="button" id="fl-load-url-btn" class="btn btn-primary">Load metadata</button>
      </div>
    </div>

    <div class="fl-edit-meta">
      <h3 class="fl-edit-meta-heading">Metadata to apply${hasEdits ? '' : ' <span class="hint" style="font-weight:400;font-size:0.8rem">— click a search result or load a URL to populate</span>'}</h3>
      <div class="fl-edit-layout">
        <div class="fl-edit-artwork">
          <div class="fl-edit-artwork-preview" id="fl-edit-art-preview">${artPreview}</div>
          <div class="field-row" style="margin-top:0.4rem">
            <label for="fl-edit-artwork-url" style="font-size:0.8rem">Artwork URL</label>
            <input type="url" id="fl-edit-artwork-url" placeholder="https://… (direct image link)" value="${esc(artUrl)}" />
          </div>
        </div>
        <div class="fl-edit-fields">
          <div class="field-row">
            <label for="fl-edit-title">Title</label>
            <input type="text" id="fl-edit-title" value="${esc(edit.title || "")}" placeholder="${esc(tags.title || "")}" />
          </div>
          <div class="field-row">
            <label for="fl-edit-artist">Artist</label>
            <input type="text" id="fl-edit-artist" value="${esc(edit.artist || "")}" placeholder="${esc(tags.artist || "")}" />
          </div>
          <div class="field-row">
            <label for="fl-edit-albumartist">Album Artist</label>
            <input type="text" id="fl-edit-albumartist" value="${esc(edit.album_artist || "")}" placeholder="${esc(tags.albumartist || "")}" />
          </div>
          <div class="field-row">
            <label for="fl-edit-album">Album</label>
            <input type="text" id="fl-edit-album" value="${esc(edit.album || "")}" placeholder="${esc(tags.album || "")}" />
          </div>
          <div class="field-row inline-fields">
            <div class="field-row">
              <label for="fl-edit-year">Year</label>
              <input type="text" id="fl-edit-year" value="${esc(edit.date || "")}" placeholder="${esc(tags.date || "")}" />
            </div>
            <div class="field-row">
              <label for="fl-edit-genre">Genre</label>
              <input type="text" id="fl-edit-genre" value="${esc(edit.genre || "")}" placeholder="${esc(tags.genre || "")}" />
            </div>
          </div>
          <div class="field-row inline-fields">
            <div class="field-row">
              <label for="fl-edit-label">Label</label>
              <input type="text" id="fl-edit-label" value="${esc(edit.label || "")}" placeholder="" />
            </div>
            <div class="field-row">
              <label for="fl-edit-catno">Cat No.</label>
              <input type="text" id="fl-edit-catno" value="${esc(edit.catno || "")}" placeholder="" />
            </div>
          </div>
          <div class="field-row">
            <label for="fl-edit-comment">Comment</label>
            <textarea id="fl-edit-comment" rows="2" placeholder="">${esc(edit.comment || "")}</textarea>
          </div>
        </div>
      </div>
    </div>

    <div class="fl-detail-actions">
      <label class="inline" style="display:inline-flex;align-items:center;gap:0.35rem">
        <input type="checkbox" id="fl-rename" ${item.rename ? "checked" : ""} />
        <span>Rename to <code>Artist - Title</code></span>
      </label>
      <button type="button" id="fl-apply-one-btn" class="btn btn-accent">Apply to this track</button>
      <div class="fl-nav-btns">
        <button type="button" id="fl-prev-btn" class="btn btn-secondary btn-sm"${prevDisabled}>&larr; Prev</button>
        <button type="button" id="fl-next-btn" class="btn btn-secondary btn-sm"${nextDisabled}>Next &rarr;</button>
      </div>
    </div>
    <div class="fl-detail-result" id="fl-detail-status"></div>
  </div>`;

  bindDetailEvents(item, results);
}

function readEditFields() {
  return {
    title: (document.getElementById("fl-edit-title")?.value || "").trim(),
    artist: (document.getElementById("fl-edit-artist")?.value || "").trim(),
    album_artist: (document.getElementById("fl-edit-albumartist")?.value || "").trim(),
    album: (document.getElementById("fl-edit-album")?.value || "").trim(),
    date: (document.getElementById("fl-edit-year")?.value || "").trim(),
    genre: (document.getElementById("fl-edit-genre")?.value || "").trim(),
    label: (document.getElementById("fl-edit-label")?.value || "").trim(),
    catno: (document.getElementById("fl-edit-catno")?.value || "").trim(),
    comment: (document.getElementById("fl-edit-comment")?.value || "").trim(),
    artwork_url: (document.getElementById("fl-edit-artwork-url")?.value || "").trim(),
  };
}

function populateEditFields(meta) {
  if (selectedIdx < 0) return;
  const item = fixListAll[selectedIdx];
  const edit = {};
  if (meta.title) edit.title = meta.title;
  if (meta.artist) edit.artist = meta.artist;
  if (meta.album_artist || meta.albumartist) edit.album_artist = meta.album_artist || meta.albumartist;
  if (meta.album) edit.album = meta.album;
  if (meta.date || meta.year) edit.date = meta.date || meta.year;
  if (meta.genre) edit.genre = meta.genre;
  if (meta.label) edit.label = meta.label;
  if (meta.catno) edit.catno = meta.catno;
  if (meta.comment) edit.comment = meta.comment;
  if (meta.artwork_url) edit.artwork_url = meta.artwork_url;
  item.editMeta = edit;
  scheduleSave();
  renderDetail();
  requestAnimationFrame(() => {
    const section = document.querySelector(".fl-edit-meta");
    if (section) section.scrollIntoView({ behavior: "smooth", block: "start" });
  });
}

function fetchHiResArtwork(sourceUrl, idx, item, artworkOnly) {
  const gen = ++artworkFetchGen;
  fetch("/api/fetch-metadata", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url: sourceUrl, track_name: item.title_hint || item.query || "" }),
  })
    .then((resp) => resp.json())
    .then((data) => {
      if (selectedIdx !== idx || gen !== artworkFetchGen) return;
      if (data.artwork_url) {
        fixListAll[idx].editMeta.artwork_url = data.artwork_url;
        const urlInput = document.getElementById("fl-edit-artwork-url");
        if (urlInput) urlInput.value = data.artwork_url;
        const prev = document.getElementById("fl-edit-art-preview");
        if (prev) prev.innerHTML = `<img src="${esc(data.artwork_url)}" alt="artwork" style="width:100%;height:100%;object-fit:cover;border-radius:var(--radius-sm)" />`;
      } else {
        const prev = document.getElementById("fl-edit-art-preview");
        if (prev) {
          const thumb = fixListAll[idx].editMeta.artwork_url || "";
          prev.innerHTML = thumb
            ? `<img src="${esc(thumb)}" alt="artwork" style="width:100%;height:100%;object-fit:cover;border-radius:var(--radius-sm)" />`
            : "<span>No artwork</span>";
        }
      }
      if (!artworkOnly) {
        if (data.genre && !fixListAll[idx].editMeta.genre) {
          fixListAll[idx].editMeta.genre = data.genre;
          const g = document.getElementById("fl-edit-genre");
          if (g) g.value = data.genre;
        }
        if (data.label && !fixListAll[idx].editMeta.label) {
          fixListAll[idx].editMeta.label = data.label;
          const l = document.getElementById("fl-edit-label");
          if (l) l.value = data.label;
        }
        if (data.catno && !fixListAll[idx].editMeta.catno) {
          fixListAll[idx].editMeta.catno = data.catno;
          const c = document.getElementById("fl-edit-catno");
          if (c) c.value = data.catno;
        }
      }
      scheduleSave();
    })
    .catch(() => {
      if (selectedIdx !== idx || gen !== artworkFetchGen) return;
      const prev = document.getElementById("fl-edit-art-preview");
      if (prev) {
        const thumb = fixListAll[idx].editMeta.artwork_url || "";
        prev.innerHTML = thumb
          ? `<img src="${esc(thumb)}" alt="artwork" style="width:100%;height:100%;object-fit:cover;border-radius:var(--radius-sm)" />`
          : "<span>No artwork</span>";
      }
    });
}

async function loadMetadataFromUrl() {
  if (selectedIdx < 0) return;
  const item = fixListAll[selectedIdx];
  const url = (document.getElementById("fl-manual-url")?.value || "").trim();
  if (!url) {
    showDetailStatus("Enter a URL first.", true);
    return;
  }
  item.manualUrl = url;

  const btn = document.getElementById("fl-load-url-btn");
  if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> Loading…'; }

  let data;
  try {
    const resp = await fetch("/api/fetch-metadata", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, track_name: item.title_hint || item.query || "" }),
    });
    data = await resp.json();
  } catch (e) {
    if (btn) { btn.disabled = false; btn.textContent = "Load metadata"; }
    showDetailStatus(String(e.message || e), true);
    return;
  }
  if (btn) { btn.disabled = false; btn.textContent = "Load metadata"; }

  if (data.error) {
    showDetailStatus(data.error, true);
    return;
  }

  item.selectedUrl = url;
  populateEditFields(data);
  showDetailStatus("Metadata loaded — edit fields as needed, then Apply.", false);
}

function bindDetailEvents(item, results) {
  document.getElementById("fl-fetch-one-btn")?.addEventListener("click", () => void fetchMatchesForCurrent());
  document.getElementById("fl-apply-one-btn")?.addEventListener("click", () => void applyToCurrentTrack());
  document.getElementById("fl-load-url-btn")?.addEventListener("click", () => void loadMetadataFromUrl());
  document.getElementById("fl-prev-btn")?.addEventListener("click", () => {
    if (selectedIdx > 0) {
      selectTrack(selectedIdx - 1);
      document.getElementById("fl-review-card")?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  });
  document.getElementById("fl-next-btn")?.addEventListener("click", () => {
    const next = findNextTrack(selectedIdx);
    if (next >= 0) {
      selectTrack(next);
      document.getElementById("fl-review-card")?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  });
  document.getElementById("fl-query")?.addEventListener("change", () => {
    fixListAll[selectedIdx].query = document.getElementById("fl-query").value.trim();
    scheduleSave();
  });
  document.getElementById("fl-manual-url")?.addEventListener("input", () => {
    fixListAll[selectedIdx].manualUrl = document.getElementById("fl-manual-url").value.trim();
    scheduleSave();
  });
  document.getElementById("fl-rename")?.addEventListener("change", (e) => {
    fixListAll[selectedIdx].rename = e.target.checked;
    scheduleSave();
  });

  // Persist edits on change
  const editIds = [
    "fl-edit-title", "fl-edit-artist", "fl-edit-albumartist", "fl-edit-album",
    "fl-edit-year", "fl-edit-genre", "fl-edit-label", "fl-edit-catno", "fl-edit-comment",
    "fl-edit-artwork-url",
  ];
  editIds.forEach((id) => {
    document.getElementById(id)?.addEventListener("input", () => {
      fixListAll[selectedIdx].editMeta = readEditFields();
      scheduleSave();
      if (id === "fl-edit-artwork-url") {
        const url = document.getElementById("fl-edit-artwork-url").value.trim();
        const preview = document.getElementById("fl-edit-art-preview");
        if (preview) {
          preview.innerHTML = url
            ? `<img src="${esc(url)}" alt="Artwork preview" style="width:100%;height:100%;object-fit:cover;border-radius:var(--radius-sm)" />`
            : "<span>No artwork</span>";
        }
      }
    });
  });

  document.querySelectorAll("#fl-detail-results .search-item").forEach((el) => {
    el.addEventListener("click", (e) => {
      if (e.target.closest("a")) return;
      const ri = parseInt(el.dataset.ridx, 10);
      const r = results[ri];
      if (!r) return;
      const idx = selectedIdx;
      const clickedThumb = !!e.target.closest(".search-thumb");
      const hasExisting = !!(fixListAll[idx].editMeta && (fixListAll[idx].editMeta.title || fixListAll[idx].editMeta.artist || fixListAll[idx].editMeta.artwork_url));

      if (!hasExisting) {
        // First pick — load everything from this result
        fixListAll[idx].selectedUrl = (r.url || "").trim();
        fixListAll[idx].manualUrl = "";
        populateEditFields({
          title: r.title || "",
          artist: r.artist || "",
          album: r.album || "",
          date: r.year || "",
          genre: r.genre || "",
          label: r.label || "",
          catno: r.catno || "",
          artwork_url: r.artwork_thumb || "",
        });
        const sourceUrl = (r.url || "").trim();
        if (sourceUrl) {
          const artPreview = document.getElementById("fl-edit-art-preview");
          if (artPreview) artPreview.innerHTML = '<span class="spinner"></span> Loading hi-res…';
          fetchHiResArtwork(sourceUrl, idx, item, false);
        }
      } else if (clickedThumb) {
        // Second pick, thumbnail — replace artwork only
        const edit = fixListAll[idx].editMeta || {};
        edit.artwork_url = r.artwork_thumb || "";
        fixListAll[idx].editMeta = edit;
        scheduleSave();
        renderDetail();
        requestAnimationFrame(() => {
          const section = document.querySelector(".fl-edit-meta");
          if (section) section.scrollIntoView({ behavior: "smooth", block: "start" });
        });
        const sourceUrl = (r.url || "").trim();
        if (sourceUrl) {
          const artPreview = document.getElementById("fl-edit-art-preview");
          if (artPreview) artPreview.innerHTML = '<span class="spinner"></span> Loading hi-res…';
          fetchHiResArtwork(sourceUrl, idx, item, true);
        }
      } else {
        // Second pick, text — replace text metadata only, keep existing artwork
        const existingArt = (fixListAll[idx].editMeta || {}).artwork_url || "";
        fixListAll[idx].selectedUrl = (r.url || "").trim();
        fixListAll[idx].manualUrl = "";
        populateEditFields({
          title: r.title || "",
          artist: r.artist || "",
          album: r.album || "",
          date: r.year || "",
          genre: r.genre || "",
          label: r.label || "",
          catno: r.catno || "",
          artwork_url: existingArt,
        });
      }
    });
  });
}

function findNextTrack(fromIdx) {
  for (let i = fromIdx + 1; i < fixListAll.length; i++) {
    if (fixListAll[i].file_exists) return i;
  }
  return -1;
}

// ── Background queue ──

function nextUnfetchedIdx() {
  // Priority track first
  if (priorityIdx >= 0 && priorityIdx < fixListAll.length) {
    const it = fixListAll[priorityIdx];
    if (it.file_exists && it.query && !it.fetched) return priorityIdx;
    priorityIdx = -1;
  }
  for (let i = 0; i < fixListAll.length; i++) {
    const it = fixListAll[i];
    if (it.file_exists && it.query && !it.fetched) return i;
  }
  return -1;
}

async function fetchOneTrack(idx) {
  const item = fixListAll[idx];
  if (!item || !item.file_exists || !item.query) return;

  currentlyFetchingIdx = idx;
  renderTrackList();
  if (selectedIdx === idx) renderDetail();

  let data;
  try {
    const resp = await fetch("/api/fix-list/suggest", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ items: [{ filepath: item.full_path, query: item.query, title_hint: item.title_hint || "" }] }),
    });
    data = await resp.json();
  } catch (e) {
    item.fetched = true;
    item.results = [];
    item.fetchError = String(e.message || e);
    currentlyFetchingIdx = -1;
    renderTrackList();
    if (selectedIdx === idx) renderDetail();
    scheduleSave();
    return;
  }

  const got = (data.items || [])[0];
  if (got && !got.error) {
    item.results = got.results || [];
    item.fetchError = null;
    item.selectedUrl = pickBestMatch(item);
    item.manualUrl = "";
  } else {
    item.results = [];
    item.fetchError = (got && got.error) || "Search failed";
    item.selectedUrl = "";
  }
  item.fetched = true;

  if (priorityIdx === idx) priorityIdx = -1;
  currentlyFetchingIdx = -1;
  renderTrackList();
  if (selectedIdx === idx) renderDetail();
  scheduleSave();
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function batchLimitReached() {
  const fetched = fixListAll.filter((it) => it.fetched).length;
  const done = completedPaths.length;
  const total = fixListAll.filter((it) => it.file_exists && it.query).length;
  if (fetched >= total) return false;
  if (fetched < BATCH_SIZE) return false;
  const unworked = fetched - done;
  return unworked > Math.ceil(BATCH_SIZE * (1 - BATCH_RESUME_PCT));
}

async function runQueue() {
  if (queueRunning) return;
  queueRunning = true;
  queueAbort = false;
  updateQueueStatus();
  setProgress(true, "Searching for matches in background…");

  while (!queueAbort) {
    if (batchLimitReached()) {
      setProgress(false);
      updateQueueStatus();
      break;
    }
    const idx = nextUnfetchedIdx();
    if (idx < 0) break;
    await fetchOneTrack(idx);
    if (queueAbort) break;
    await sleep(1000);
  }

  queueRunning = false;
  currentlyFetchingIdx = -1;
  setProgress(false);
  updateQueueStatus();
  renderTrackList();
  if (selectedIdx >= 0) renderDetail();
  saveState();
}

function stopQueue() {
  queueAbort = true;
}

// ── Upload ──

async function uploadCSV() {
  const fileInput = $("#fl-csv-input");
  if (!fileInput.files || !fileInput.files.length) {
    setStatus("Choose a CSV file first.", true);
    return;
  }

  stopQueue();
  setStatus("");
  setProgress(true, "Uploading and scanning files…");

  const form = new FormData();
  form.append("file", fileInput.files[0]);

  let data;
  try {
    const resp = await fetch("/api/fix-list/upload", { method: "POST", body: form });
    data = await resp.json();
  } catch (e) {
    setProgress(false);
    setStatus(String(e.message || e), true);
    return;
  }
  setProgress(false);

  if (data.error) { setStatus(data.error, true); return; }

  fixListAll = (data.items || []).map((item) => ({
    ...item,
    results: [],
    selectedUrl: "",
    manualUrl: "",
    fetchError: null,
    rename: false,
    fetched: false,
    editMeta: {},
  }));
  completedPaths = [];
  selectedIdx = -1;

  showSummary(data.summary);
  setStatus(`Loaded ${fixListAll.length} track(s). Searching for matches in background…`, false);

  $("#fl-review-card")?.classList.remove("hidden");
  $("#fl-detail-card")?.classList.remove("hidden");
  $("#fl-apply-card")?.classList.remove("hidden");
  updateExportCard();

  renderTrackList();
  renderDetail();
  saveState();

  void runQueue();
}

// ── Fetch matches (single track, jump the queue) ──

async function fetchMatchesForCurrent() {
  if (selectedIdx < 0) return;
  const item = fixListAll[selectedIdx];
  if (!item.file_exists) return;

  const query = (document.getElementById("fl-query")?.value || item.query || "").trim();
  if (!query) {
    showDetailStatus("Enter a search query first.", true);
    return;
  }
  item.query = query;
  item.fetched = false;

  if (queueRunning) {
    // Set priority so queue picks this one next, then let the queue handle it
    priorityIdx = selectedIdx;
    renderDetail();
    return;
  }

  // Queue not running — fetch directly
  await fetchOneTrack(selectedIdx);
}

// ── Apply to current track ──

async function applyToCurrentTrack() {
  if (selectedIdx < 0) return;
  const item = fixListAll[selectedIdx];
  if (!item.file_exists) return;

  const edit = readEditFields();
  const hasFields = edit.title || edit.artist || edit.album || edit.artwork_url;
  if (!hasFields) {
    showDetailStatus("Load metadata first — click a search result or paste a URL.", true);
    return;
  }

  const rename = document.getElementById("fl-rename")?.checked || false;
  const sourceUrl = (item.selectedUrl || item.manualUrl || "").trim();

  const btn = document.getElementById("fl-apply-one-btn");
  if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> Applying…'; }

  const metadata = {};
  if (edit.title) metadata.title = edit.title;
  if (edit.artist) metadata.artist = edit.artist;
  if (edit.album_artist) metadata.albumartist = edit.album_artist;
  if (edit.album) metadata.album = edit.album;
  if (edit.date) metadata.date = edit.date;
  if (edit.genre) metadata.genre = edit.genre;
  if (edit.label) metadata.label = edit.label;
  if (edit.catno) metadata.catno = edit.catno;
  if (edit.comment) metadata.comment = edit.comment;

  const body = {
    filepath: item.full_path,
    metadata,
    artwork_url: edit.artwork_url || "",
    metadata_source_url: sourceUrl,
    rename_to_tags: rename,
    record_in_log: true,
  };

  let data;
  try {
    const resp = await fetch("/api/retag", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    data = await resp.json();
  } catch (e) {
    if (btn) { btn.disabled = false; btn.textContent = "Apply to this track"; }
    showDetailStatus(String(e.message || e), true);
    return;
  }
  if (btn) { btn.disabled = false; btn.textContent = "Apply to this track"; }

  if (data.error) {
    showDetailStatus(data.error, true);
    return;
  }

  if (data.status === "ok") {
    const finalPath = data.filepath || item.full_path;
    if (!completedPaths.includes(finalPath)) completedPaths.push(finalPath);
    if (data.renamed && data.filepath !== item.full_path) {
      item.full_path = data.filepath;
      item.file_name = data.filepath.split("/").pop();
    }
    showDetailStatus("Metadata applied successfully.", false);
    updateExportCard();

    try {
      const tagResp = await fetch("/api/fix-list/upload", {
        method: "POST",
        body: (() => {
          const f = new FormData();
          const csvLine = `full_path\n${item.full_path}`;
          f.append("file", new Blob([csvLine], { type: "text/csv" }), "re-read.csv");
          return f;
        })(),
      });
      const tagData = await tagResp.json();
      if (tagData.items && tagData.items[0]) {
        fixListAll[selectedIdx].actual_tags = tagData.items[0].actual_tags;
      }
    } catch (_) { /* non-critical */ }
  } else {
    showDetailStatus(data.error || "Error applying metadata.", true);
  }

  renderTrackList();
  renderDetail();
  saveState();

  if (!queueRunning && !batchLimitReached()) {
    const remaining = fixListAll.filter((it) => it.file_exists && it.query && !it.fetched).length;
    if (remaining > 0) void runQueue();
  }
}

function showDetailStatus(text, isError) {
  const el = document.getElementById("fl-detail-status");
  if (!el) return;
  el.className = "fl-detail-result " + (isError ? "status error" : "status");
  el.textContent = text;
}

// ── Export ──

function updateExportCard(statusOverride) {
  const summary = $("#fl-completed-summary");
  const btn = $("#fl-export-btn");
  const newBtn = $("#fl-export-new-btn");
  const newCount = completedPaths.filter((p) => !exportedPaths.has(p)).length;
  if (summary) {
    if (statusOverride) {
      summary.textContent = statusOverride;
    } else {
      let text = completedPaths.length
        ? `${completedPaths.length} track(s) fixed so far.`
        : "No tracks fixed yet. Apply metadata to tracks above.";
      if (exportedPaths.size > 0 && newCount > 0) {
        text += ` ${newCount} new since last export.`;
      }
      summary.textContent = text;
    }
  }
  if (btn) btn.disabled = !completedPaths.length;
  if (newBtn) newBtn.disabled = newCount === 0;
}

async function exportToServer(paths, filenamePrefix) {
  if (!paths.length) return null;
  try {
    const resp = await fetch("/api/fix-list/export-completed", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ paths, filename: `${filenamePrefix}_${new Date().toISOString().slice(0, 10).replace(/-/g, "")}` }),
    });
    const data = await resp.json();
    if (data.error) return null;
    return data;
  } catch (e) {
    return null;
  }
}

async function exportCompletedCSV() {
  if (!completedPaths.length) return;
  const result = await exportToServer(completedPaths, "completed_fixes");
  if (result) {
    completedPaths.forEach((p) => exportedPaths.add(p));
    updateExportCard(`Saved ${result.count} path(s) to ${result.filepath}`);
    scheduleSave();
  } else {
    updateExportCard("Export failed — check server logs.");
  }
}

async function exportNewCSV() {
  const newPaths = completedPaths.filter((p) => !exportedPaths.has(p));
  if (!newPaths.length) return;
  const result = await exportToServer(newPaths, "completed_fixes_new");
  if (result) {
    newPaths.forEach((p) => exportedPaths.add(p));
    updateExportCard(`Saved ${result.count} new path(s) to ${result.filepath}`);
    scheduleSave();
  } else {
    updateExportCard("Export failed — check server logs.");
  }
}

// ── Clear ──

function clearAll() {
  stopQueue();
  fixListAll = [];
  selectedIdx = -1;
  completedPaths = [];
  exportedPaths = new Set();
  currentlyFetchingIdx = -1;
  priorityIdx = -1;
  $("#fl-csv-input").value = "";
  setStatus("");
  setProgress(false);
  $("#fl-summary")?.classList.add("hidden");
  $("#fl-review-card")?.classList.add("hidden");
  $("#fl-detail-card")?.classList.add("hidden");
  $("#fl-apply-card")?.classList.add("hidden");
  fetch("/api/fix-list/state", { method: "DELETE" }).catch(() => {});
}

// ── Restore ──

async function restoreState() {
  let state = null;
  try {
    const resp = await fetch("/api/fix-list/state");
    const data = await resp.json();
    state = data.state;
  } catch (_) { return; }
  if (!state || ![2, 3, 4].includes(state.v) || !Array.isArray(state.fixListAll) || !state.fixListAll.length) return;

  fixListAll = state.fixListAll;
  completedPaths = Array.isArray(state.completedPaths) ? state.completedPaths : [];
  exportedPaths = new Set(Array.isArray(state.exportedPaths) ? state.exportedPaths : []);
  selectedIdx = typeof state.selectedIdx === "number" ? state.selectedIdx : -1;

  fixListAll.forEach((it) => {
    if (it.fetched === undefined) {
      it.fetched = (it.results || []).length > 0 || !!it.fetchError;
    }
    if (!it.editMeta) it.editMeta = {};
  });

  showSummary({
    total: fixListAll.length,
    files_found: fixListAll.filter((i) => i.file_exists).length,
    files_missing: fixListAll.filter((i) => !i.file_exists).length,
    needs_tags: fixListAll.filter((i) => i.file_exists && (!(i.actual_tags?.title || "").trim() || !(i.actual_tags?.artist || "").trim())).length,
    needs_artwork: fixListAll.filter((i) => i.file_exists && !i.actual_tags?.has_artwork).length,
  });

  const unfetched = fixListAll.filter((it) => it.file_exists && it.query && !it.fetched).length;
  if (unfetched > 0) {
    setStatus(`Restored ${fixListAll.length} track(s). Resuming search for ${unfetched} remaining…`, false);
  } else {
    setStatus(`Restored ${fixListAll.length} track(s) from previous session.`, false);
  }

  $("#fl-review-card")?.classList.remove("hidden");
  $("#fl-detail-card")?.classList.remove("hidden");
  $("#fl-apply-card")?.classList.remove("hidden");
  updateExportCard();
  renderTrackList();
  renderDetail();

  if (unfetched > 0) {
    void runQueue();
  }
}

// ── Keyboard nav ──

document.getElementById("fl-track-list")?.addEventListener("keydown", (e) => {
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault();
    let next = selectedIdx;
    const dir = e.key === "ArrowDown" ? 1 : -1;
    for (let i = selectedIdx + dir; i >= 0 && i < fixListAll.length; i += dir) {
      if (fixListAll[i].file_exists) { next = i; break; }
    }
    if (next !== selectedIdx && next >= 0) selectTrack(next);
  }
});

// ── Button bindings ──

document.getElementById("fl-upload-btn")?.addEventListener("click", () => void uploadCSV());
document.getElementById("fl-clear-btn")?.addEventListener("click", clearAll);
document.getElementById("fl-export-btn")?.addEventListener("click", exportCompletedCSV);
document.getElementById("fl-export-new-btn")?.addEventListener("click", exportNewCSV);

void restoreState();
