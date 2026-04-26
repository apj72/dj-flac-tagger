const $ = (sel) => document.querySelector(sel);
const BF_DIR_LS = "djmm.bulkFixDir";
const BF_STATE_LS = "djmm.bulkFixState";

let folderModalPath = "";
/** Current batch rows (from last successful load) */
let batchRows = [];
/** Last successful scan: offset, page size, total (for next-offset UI + restore) */
let lastBfScanMeta = null;
let bfSaveTimer = null;

function esc(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function closeFolderModal() {
  const el = document.getElementById("bf-folder-modal");
  if (el) el.classList.add("hidden");
  document.removeEventListener("keydown", onFolderModalKeydown);
}

function onFolderModalKeydown(e) {
  if (e.key === "Escape") closeFolderModal();
}

async function openFolderModal() {
  let start = $("#bf-dir").value.trim();
  if (!start) {
    const resp = await fetch("/api/settings");
    const cfg = await resp.json();
    start = (cfg.destination_dir || "").trim() || "~";
  }
  document.getElementById("bf-folder-modal").classList.remove("hidden");
  document.addEventListener("keydown", onFolderModalKeydown);
  await loadFolderInModal(start);
}

async function loadFolderInModal(path) {
  const listEl = $("#bf-modal-dir-list");
  const pathEl = $("#bf-modal-path");
  const upBtn = $("#bf-modal-up");
  listEl.innerHTML = '<div class="status">Loading…</div>';
  upBtn.disabled = true;

  const resp = await fetch(`/api/browse-folders?path=${encodeURIComponent(path)}`);
  const data = await resp.json();
  if (data.error) {
    listEl.innerHTML = `<div class="status">${esc(data.error)}</div>`;
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

async function resetDirToDefault() {
  const resp = await fetch("/api/settings");
  const cfg = await resp.json();
  $("#bf-dir").value = (cfg.destination_dir || "").trim();
}

function setBatchUiEnabled(hasBatch) {
  document.getElementById("bf-fetch-matches-btn").disabled = !hasBatch;
  document.getElementById("bf-apply-btn").disabled = !hasBatch;
}

function setBfProgress(wrapId, visible, label) {
  const wrap = document.getElementById(wrapId);
  const lab = wrapId === "bf-progress-wrap" ? document.getElementById("bf-progress-label") : document.getElementById("bf-step3-progress-label");
  if (!wrap) return;
  wrap.classList.toggle("hidden", !visible);
  if (lab && label) lab.textContent = label;
}

function nth(n) {
  const s = n % 100;
  if (s >= 11 && s <= 13) return "th";
  switch (n % 10) {
    case 1:
      return "st";
    case 2:
      return "nd";
    case 3:
      return "rd";
    default:
      return "th";
  }
}

/** Lowercase alphanumeric tokens (length > 1) for fuzzy compare */
function bfNormTokens(s) {
  return new Set(
    String(s || "")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, " ")
      .trim()
      .split(/\s+/)
      .filter((w) => w.length > 1),
  );
}

function bfTokenOverlap(a, b) {
  if (!a.size || !b.size) return 0;
  let n = 0;
  for (const t of a) {
    if (b.has(t)) n += 1;
  }
  return n;
}

function bfCompactAlnum(s) {
  return String(s || "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "");
}

function scoreBulkFixResult(row, r, index, nResults) {
  const url = (r.url || "").trim();
  if (!url) return -1e9;
  const titleT = bfNormTokens(r.title);
  const artistT = bfNormTokens(r.artist || "");
  const albumT = bfNormTokens(r.album || "");
  const cand = new Set([...titleT, ...artistT, ...albumT]);
  const hintTitle = bfNormTokens(row.title_hint);
  const hintArtist = bfNormTokens(row.artist_hint);
  const hintQuery = bfNormTokens(row.query);
  let score = 0;
  score += bfTokenOverlap(hintTitle, titleT) * 5;
  score += bfTokenOverlap(hintArtist, artistT) * 5;
  score += bfTokenOverlap(hintTitle, cand) * 2;
  score += bfTokenOverlap(hintArtist, cand) * 2;
  score += bfTokenOverlap(hintQuery, cand) * 1.2;
  const thc = bfCompactAlnum(row.title_hint);
  const tac = bfCompactAlnum([r.title, r.artist, r.album].filter(Boolean).join(" "));
  if (thc.length >= 4 && tac.includes(thc)) score += 6;
  const ahc = bfCompactAlnum(row.artist_hint);
  if (ahc.length >= 4 && tac.includes(ahc)) score += 4;
  const src = String(r.source || "").toLowerCase();
  if (src === "apple_music" || src === "itunes") score += 1.2;
  else if (src === "discogs") score += 1;
  else if (src === "bandcamp") score += 0.6;
  score += (nResults - index) * 0.04;
  return score;
}

/** Pick the suggestion URL that best matches filename hints / query; ties favor API order (Apple-first list). */
function pickBestBulkFixMatch(row) {
  const results = row.results || [];
  const n = results.length;
  let bestUrl = "";
  let bestScore = -1e9;
  for (let i = 0; i < n; i += 1) {
    const r = results[i];
    const u = (r.url || "").trim();
    if (!u) continue;
    const sc = scoreBulkFixResult(row, r, i, n);
    if (sc > bestScore) {
      bestScore = sc;
      bestUrl = u;
    }
  }
  return bestUrl;
}

function bfDuplicateTooltip(row) {
  if (!row.duplicate_basename) return "";
  const n = row.same_basename_count || 1;
  const others = row.same_basename_other_paths || [];
  const lines = [`This filename appears ${n} time(s) under the scanned folder (including this file).`];
  if (others.length) {
    lines.push("Other path(s):");
    others.forEach((p) => lines.push(p));
  }
  return lines.join("\n");
}

function saveBulkFixState() {
  try {
    const st = $("#bf-range-status");
    const hint = $("#bf-load-hint");
    const payload = {
      v: 1,
      dir: $("#bf-dir").value.trim(),
      recursive: $("#bf-recursive").checked !== false,
      batchSize: $("#bf-batch-size").value,
      offset: $("#bf-offset").value,
      rename: $("#bf-rename").checked === true,
      batchRows,
      lastBfScanMeta,
      rangeStatus: st ? st.textContent : "",
      loadHint: hint ? hint.textContent : "",
    };
    localStorage.setItem(BF_STATE_LS, JSON.stringify(payload));
    if (payload.dir) {
      try {
        localStorage.setItem(BF_DIR_LS, payload.dir);
      } catch (_) {
        /* ignore */
      }
    }
  } catch (_) {
    /* quota or private mode */
  }
}

function scheduleSaveBulkFixState() {
  if (bfSaveTimer) clearTimeout(bfSaveTimer);
  bfSaveTimer = setTimeout(() => {
    bfSaveTimer = null;
    saveBulkFixState();
  }, 400);
}

function restoreBulkFixStateFromStorage() {
  let state = null;
  try {
    const raw = localStorage.getItem(BF_STATE_LS);
    if (raw) state = JSON.parse(raw);
  } catch (_) {
    return;
  }
  if (!state || state.v !== 1 || !state.dir) {
    const s = localStorage.getItem(BF_DIR_LS);
    if (s && s.trim()) $("#bf-dir").value = s.trim();
    return;
  }
  $("#bf-dir").value = state.dir;
  $("#bf-recursive").checked = state.recursive !== false;
  if (state.batchSize != null) $("#bf-batch-size").value = String(state.batchSize);
  if (state.offset != null) $("#bf-offset").value = String(state.offset);
  $("#bf-rename").checked = !!state.rename;
  batchRows = Array.isArray(state.batchRows) ? state.batchRows : [];
  batchRows.forEach((row) => {
    if ((row.results || []).length && !(row.preferredMatchUrl || "").trim()) {
      row.preferredMatchUrl = pickBestBulkFixMatch(row);
    }
  });
  lastBfScanMeta = state.lastBfScanMeta || null;
  const st = $("#bf-range-status");
  const hint = $("#bf-load-hint");
  if (st && state.rangeStatus != null) st.textContent = state.rangeStatus;
  if (hint && state.loadHint != null) hint.textContent = state.loadHint;
  if (lastBfScanMeta && batchRows.length) {
    updateBfNextOffsetBox(lastBfScanMeta.off, lastBfScanMeta.itemsLen, lastBfScanMeta.total);
  } else {
    document.getElementById("bf-next-offset-box")?.classList.add("hidden");
  }
  renderTable();
  $("#bf-result").classList.add("hidden");
  try {
    localStorage.setItem(BF_DIR_LS, state.dir);
  } catch (_) {
    /* ignore */
  }
}

function applyBfQueryOffsetLimit(qp) {
  const offQ = qp.get("offset");
  if (offQ != null && offQ !== "") {
    const o = parseInt(offQ, 10);
    if (!Number.isNaN(o) && o >= 0) $("#bf-offset").value = String(o);
  }
  const limQ = qp.get("limit");
  if (limQ != null && limQ !== "") {
    const l = parseInt(limQ, 10);
    if (!Number.isNaN(l) && l >= 1 && l <= 200) $("#bf-batch-size").value = String(l);
  }
}

function initBulkFixPage() {
  const qp = new URLSearchParams(window.location.search);
  const fromQuery = (qp.get("dir") || "").trim();
  let handoff = null;
  try {
    const hr = localStorage.getItem("djmm.bulkFixHandoff");
    if (hr) handoff = JSON.parse(hr);
  } catch (_) {
    /* ignore */
  }
  const canHandoff =
    handoff &&
    handoff.v === 1 &&
    Array.isArray(handoff.paths) &&
    handoff.paths.length &&
    (handoff.targetDir || "").trim();
  if (fromQuery && canHandoff) {
    const t = (handoff.targetDir || "").replace(/\/+$/, "");
    const q = fromQuery.replace(/\/+$/, "");
    if (t === q) {
      $("#bf-dir").value = fromQuery;
      try {
        localStorage.setItem(BF_DIR_LS, fromQuery);
      } catch (_) {
        /* ignore */
      }
      void loadBatchFromConvertHandoff(handoff.paths);
      return;
    }
  }
  if (fromQuery) {
    $("#bf-dir").value = fromQuery;
    applyBfQueryOffsetLimit(qp);
    try {
      localStorage.setItem(BF_DIR_LS, fromQuery);
    } catch (_) {
      /* ignore */
    }
    void loadBatch();
    return;
  }
  restoreBulkFixStateFromStorage();
}

function updateBfNextOffsetBox(currentOff, itemsInPage, total) {
  const box = document.getElementById("bf-next-offset-box");
  if (!box) return;
  if (itemsInPage === 0) {
    box.classList.add("hidden");
    return;
  }
  const nextOff = currentOff + itemsInPage;
  const v = document.getElementById("bf-next-offset-value");
  const v1 = document.getElementById("bf-next-1-based");
  const det = document.getElementById("bf-next-offset-detail");
  if (v) v.textContent = String(nextOff);
  if (v1) v1.textContent = String(nextOff + 1);
  box.dataset.nextOffset = String(nextOff);
  if (det) {
    if (nextOff < total) {
      det.textContent = `${total} FLAC(s) total. For the next batch, set Start offset to ${nextOff} (that starts at the ${nextOff + 1}${nth(nextOff + 1)} file when counting 1, 2, 3…).`;
    } else {
      det.textContent = `You have reached the end of the list (${total} file(s)). Nothing more to load with this offset.`;
    }
  }
  box.classList.remove("hidden");
}

function renderTable() {
  const tbody = $("#bf-tbody");
  if (!batchRows.length) {
    tbody.innerHTML = '<tr><td colspan="7" class="status">No rows. Load a batch (step 2).</td></tr>';
    setBatchUiEnabled(false);
    return;
  }
  function sourceLabel(source) {
    if (source === "discogs") return "Discogs";
    if (source === "apple_music") return "Apple";
    if (source === "bandcamp") return "Bandcamp";
    return source ? String(source) : "Web";
  }
  tbody.innerHTML = batchRows
    .map((row, idx) => {
      const preferred = (row.preferredMatchUrl || "").trim();
      const opts = (row.results || []).map((r) => {
        const label = [r.title, r.artist || r.album].filter(Boolean).join(" — ");
        const u = (r.url || "").trim();
        const sel = preferred && u === preferred ? " selected" : "";
        return `<option value="${esc(u)}"${sel}>${esc(sourceLabel(r.source))}: ${esc(label).slice(0, 100)}</option>`;
      });
      const linkBits = (row.results || [])
        .map((r) => {
          const u = (r.url || "").trim();
          if (!u) return "";
          return `<a href="${esc(u)}" target="_blank" rel="noopener noreferrer" class="bf-proof-link" title="Open in new tab">${esc(
            sourceLabel(r.source)
          )}</a>`;
        })
        .filter(Boolean);
      const fullUrlLines = (row.results || [])
        .map((r) => {
          const u = (r.url || "").trim();
          if (!u) return "";
          return `<div class="bf-url-line"><a class="bf-url-raw" href="${esc(
            u
          )}" target="_blank" rel="noopener noreferrer" title="Validate this result">${esc(u)}</a></div>`;
        })
        .filter(Boolean)
        .join("");
      const openLinks = linkBits.length
        ? `<div class="bf-open-links" style="margin-top:0.2rem;line-height:1.45">${linkBits.join(
            ' <span class="hint" aria-hidden="true">·</span> '
          )}</div>
          <div class="bf-url-raw-block" style="margin-top:0.35rem">${fullUrlLines}</div>
          <p class="hint" style="font-size:0.7rem;margin:0.2rem 0 0">Short labels above; full URLs for copy or open.</p>`
        : "";
      const selectHtml =
        opts.length > 0
          ? `<select class="bf-pick" data-idx="${idx}" style="max-width:14rem;font-size:0.85rem">
              <option value="">— pick a result —</option>
              ${opts.join("")}
            </select>
            ${openLinks}`
          : row.fetchError
            ? `<span class="hint">${esc(row.fetchError)}</span>`
            : '<span class="hint">—</span>';
      const wtags = row.wav_tags || null;
      let wavCell = "—";
      if (row.wav_sibling) {
        const bits = [];
        if (wtags) {
          if (wtags.artist) bits.push(esc(wtags.artist));
          if (wtags.title) bits.push(esc(wtags.title));
          if (wtags.album) bits.push(`<span class="hint">${esc(wtags.album)}</span>`);
        }
        const inner = bits.length ? bits.join(" — ") : '<span class="hint">(no tags)</span>';
        wavCell = `<div style="font-size:0.82rem;max-width:12rem" title="${esc(row.wav_sibling)}">${inner}</div>`;
      }
      const nSame = row.same_basename_count || 1;
      const dupTip = esc(bfDuplicateTooltip(row));
      const fileCell = row.duplicate_basename
        ? `<div class="bf-file-col">
            <div class="mono bf-file-name">${esc(row.basename)}</div>
            <div class="bf-dup-line" title="${dupTip}">
              ${
                row.duplicate_in_batch
                  ? '<span class="bf-dup-pill">Duplicate in this batch</span>'
                  : '<span class="bf-dup-pill bf-dup-pill-soft">Same name elsewhere</span>'
              }
              <span class="bf-dup-meta">(${nSame}× in tree)</span>
            </div>
          </div>`
        : `<div class="bf-file-col"><div class="mono bf-file-name" style="font-size:0.8rem;word-break:break-all">${esc(
            row.basename
          )}</div></div>`;
      return `<tr data-idx="${idx}">
        <td class="th-check"><input type="checkbox" class="bf-use" data-idx="${idx}" checked /></td>
        <td class="bf-td-file">${fileCell}</td>
        <td style="vertical-align:top">${wavCell}</td>
        <td style="font-size:0.85rem">${esc(row.query)}</td>
        <td style="font-size:0.85rem">${esc(row.title_hint || "—")}</td>
        <td style="vertical-align:top;min-width:10rem">${selectHtml}</td>
        <td><input type="url" class="bf-manual" data-idx="${idx}" placeholder="https://…" style="width:100%;min-width:10rem;font-size:0.8rem" value="${esc(row.manualUrl || "")}" /></td>
      </tr>`;
    })
    .join("");

  tbody.querySelectorAll(".bf-pick").forEach((selEl) => {
    selEl.addEventListener("change", () => {
      const i = parseInt(selEl.dataset.idx, 10);
      if (Number.isNaN(i) || !batchRows[i]) return;
      batchRows[i].manualUrl = "";
      batchRows[i].preferredMatchUrl = (selEl.value || "").trim();
      const manual = tbody.querySelector(`.bf-manual[data-idx="${i}"]`);
      if (manual) manual.value = "";
      scheduleSaveBulkFixState();
    });
  });
  setBatchUiEnabled(true);
}

function mapScanItemsToBatchRows(items) {
  return items.map((it) => ({
    filepath: it.filepath,
    basename: it.basename,
    query: it.query,
    title_hint: it.title_hint || "",
    artist_hint: it.artist_hint || "",
    wav_sibling: it.wav_sibling || "",
    wav_tags: it.wav_tags || null,
    duplicate_basename: !!it.duplicate_basename,
    same_basename_count: it.same_basename_count ?? 1,
    same_basename_other_paths: it.same_basename_other_paths || [],
    duplicate_in_batch: !!it.duplicate_in_batch,
    results: [],
    manualUrl: "",
    preferredMatchUrl: "",
    fetchError: null,
  }));
}

function finalizeBulkFixScanUI(data, folderCtx) {
  const st = $("#bf-range-status");
  const hint = $("#bf-load-hint");
  const items = data.items || [];
  const total = data.total ?? 0;
  batchRows = mapScanItemsToBatchRows(items);
  const dupInView = data.duplicates_in_batch ?? 0;
  const dupTree = items.filter((it) => it.duplicate_basename).length;

  if (folderCtx && folderCtx.mode === "folder") {
    const off = folderCtx.off;
    const lim = folderCtx.lim;
    const end = off + items.length;
    st.textContent = `Folder: ${data.root} — ${total} FLAC file(s) total. Showing ${items.length ? off + 1 : 0}–${end} (offset ${off}, limit ${lim}).`;
    if (end < total) {
      hint.textContent = `Next chunk: use offset ${end} (see the highlighted box below).`;
    } else if (total > 0) {
      hint.textContent = "You are at the end of the list (or the offset is past the last file).";
    } else {
      hint.textContent = "No .flac files in this folder with the current options.";
    }
    if (dupInView > 0) {
      hint.textContent =
        (hint.textContent || "") +
        ` Warning: ${dupInView} row(s) share a filename with another row in this batch (see labels in the File column). Uncheck extras if you only want one copy tagged.`;
    } else if (dupTree > 0 && items.length) {
      hint.textContent =
        (hint.textContent || "") +
        ` Note: ${dupTree} file(s) in this batch have the same name as another file elsewhere under this folder (hover the “Same name elsewhere” label for paths).`;
    }
    lastBfScanMeta = { off, itemsLen: items.length, total, lim };
    updateBfNextOffsetBox(off, items.length, total);
  } else {
    st.textContent = `Loaded ${items.length} FLAC file(s) in bulk conversion order (not folder listing order). Folder: ${data.root}`;
    hint.textContent =
      "These files match the last WAV → FLAC batch from the Convert page. Use Load batch to page through the folder by offset when you are not using a conversion handoff.";
    if (dupInView > 0) {
      hint.textContent += ` Warning: ${dupInView} row(s) share a filename with another row in this batch.`;
    } else if (dupTree > 0 && items.length) {
      hint.textContent += ` Note: ${dupTree} file(s) have the same name as another file elsewhere under this folder.`;
    }
    lastBfScanMeta = null;
    document.getElementById("bf-next-offset-box")?.classList.add("hidden");
  }
  renderTable();
  $("#bf-result").classList.add("hidden");
  saveBulkFixState();
}

async function loadBatchFromConvertHandoff(paths) {
  const st = $("#bf-range-status");
  const hint = $("#bf-load-hint");
  st.textContent = "";
  hint.textContent = "";
  setBfProgress("bf-progress-wrap", true, "Loading FLAC paths from last conversion (same order as that batch)…");
  let data;
  try {
    const resp = await fetch("/api/bulk-fix/scan-paths", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ paths }),
    });
    data = await resp.json();
  } catch (e) {
    st.textContent = String(e.message || e);
    batchRows = [];
    lastBfScanMeta = null;
    renderTable();
    document.getElementById("bf-next-offset-box")?.classList.add("hidden");
    saveBulkFixState();
    return;
  } finally {
    setBfProgress("bf-progress-wrap", false);
  }
  if (data.error) {
    st.textContent = data.error;
    batchRows = [];
    lastBfScanMeta = null;
    renderTable();
    document.getElementById("bf-next-offset-box")?.classList.add("hidden");
    saveBulkFixState();
    return;
  }
  finalizeBulkFixScanUI(data, null);
  try {
    localStorage.removeItem("djmm.bulkFixHandoff");
  } catch (_) {
    /* ignore */
  }
}

async function loadBatch() {
  const dir = $("#bf-dir").value.trim();
  const rec = $("#bf-recursive").checked !== false;
  let lim = parseInt($("#bf-batch-size").value, 10);
  if (Number.isNaN(lim) || lim < 1) lim = 25;
  if (lim > 200) lim = 200;
  let off = parseInt($("#bf-offset").value, 10);
  if (Number.isNaN(off) || off < 0) off = 0;

  const st = $("#bf-range-status");
  const hint = $("#bf-load-hint");
  st.textContent = "";
  hint.textContent = "";
  if (!dir) {
    st.textContent = "Set a folder path first.";
    document.getElementById("bf-next-offset-box")?.classList.add("hidden");
    batchRows = [];
    lastBfScanMeta = null;
    renderTable();
    saveBulkFixState();
    return;
  }

  try {
    localStorage.setItem(BF_DIR_LS, dir);
  } catch (_) {
    /* ignore */
  }

  st.textContent = "Scanning…";
  setBfProgress("bf-progress-wrap", true, "Listing FLAC files in the folder…");
  const u = new URL("/api/bulk-fix/scan", window.location.origin);
  u.searchParams.set("path", dir);
  u.searchParams.set("recursive", rec ? "1" : "0");
  u.searchParams.set("offset", String(off));
  u.searchParams.set("limit", String(lim));

  let data;
  try {
    const resp = await fetch(u);
    data = await resp.json();
  } catch (e) {
    st.textContent = String(e.message || e);
    batchRows = [];
    lastBfScanMeta = null;
    renderTable();
    document.getElementById("bf-next-offset-box")?.classList.add("hidden");
    saveBulkFixState();
    return;
  } finally {
    setBfProgress("bf-progress-wrap", false);
  }

  if (data.error) {
    st.textContent = data.error;
    batchRows = [];
    lastBfScanMeta = null;
    renderTable();
    document.getElementById("bf-next-offset-box")?.classList.add("hidden");
    saveBulkFixState();
    return;
  }

  finalizeBulkFixScanUI(data, { mode: "folder", off, lim });
}

async function fetchMatches() {
  if (!batchRows.length) return;
  const status = $("#bf-fetch-status");
  const btn = $("#bf-fetch-matches-btn");
  status.classList.remove("hidden");
  status.textContent = "";
  btn.disabled = true;
  setBfProgress("bf-step3-progress-wrap", true, "Searching Apple Music and Discogs (one file at a time on the server)…");

  const paths = batchRows.map((r) => r.filepath);
  let data;
  try {
    const resp = await fetch("/api/bulk-fix/suggest", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ paths }),
    });
    data = await resp.json();
  } catch (e) {
    setBfProgress("bf-step3-progress-wrap", false);
    status.classList.remove("hidden");
    status.textContent = String(e.message || e);
    btn.disabled = false;
    return;
  }
  setBfProgress("bf-step3-progress-wrap", false);
  btn.disabled = false;
  status.classList.add("hidden");

  if (data.error) {
    status.classList.remove("hidden");
    status.textContent = data.error;
    return;
  }

  const byPath = {};
  (data.items || []).forEach((it) => {
    byPath[it.filepath] = it;
  });

  batchRows.forEach((row) => {
    const got = byPath[row.filepath];
    row.results = got && !got.error ? got.results || [] : [];
    if (got && got.error) {
      row.fetchError = got.error;
      row.preferredMatchUrl = "";
    } else {
      row.fetchError = null;
      row.preferredMatchUrl = pickBestBulkFixMatch(row);
    }
  });

  renderTable();
  status.classList.remove("hidden");
  status.textContent =
    "Matches loaded. A best guess is pre-selected in each row — change any dropdown or paste a URL if it looks wrong.";
  setTimeout(() => status.classList.add("hidden"), 5000);
  saveBulkFixState();
}

function collectApplyPayload() {
  const tbody = $("#bf-tbody");
  const items = [];
  batchRows.forEach((row, idx) => {
    const use = tbody.querySelector(`.bf-use[data-idx="${idx}"]`);
    if (!use || !use.checked) return;
    const manual = tbody.querySelector(`.bf-manual[data-idx="${idx}"]`);
    const pick = tbody.querySelector(`.bf-pick[data-idx="${idx}"]`);
    let url = (manual && manual.value.trim()) || "";
    if (!url && pick && pick.value) url = pick.value.trim();
    if (!url) return;
    items.push({
      filepath: row.filepath,
      source_url: url,
      title_hint: row.title_hint || "",
    });
  });
  return items;
}

async function applySelected() {
  const items = collectApplyPayload();
  const out = $("#bf-result");
  if (!items.length) {
    out.className = "result error";
    out.classList.remove("hidden");
    out.innerHTML =
      '<div class="result-title">Nothing to apply</div><div class="result-detail">Check at least one row and choose a match or enter a URL.</div>';
    return;
  }
  const tbody0 = $("#bf-tbody");
  let dupSelected = 0;
  batchRows.forEach((row, idx) => {
    const use = tbody0.querySelector(`.bf-use[data-idx="${idx}"]`);
    if (!use || !use.checked) return;
    if (row.duplicate_basename) dupSelected += 1;
  });
  let confirmMsg = `Apply metadata to ${items.length} file(s) from the selected sources?`;
  if (dupSelected > 0) {
    confirmMsg += `\n\n${dupSelected} selected row(s) have the same filename as another file under this folder (see File column). Continue only if you want those copies tagged.`;
  }
  if (!window.confirm(confirmMsg)) return;

  out.classList.add("hidden");
  const btn = $("#bf-apply-btn");
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Applying…';
  setBfProgress("bf-step3-progress-wrap", true, "Fetching metadata and writing tags to FLAC…");

  let data;
  try {
    const resp = await fetch("/api/bulk-fix/apply", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        items,
        rename_to_tags: $("#bf-rename").checked === true,
        record_in_log: true,
      }),
    });
    data = await resp.json();
  } catch (e) {
    setBfProgress("bf-step3-progress-wrap", false);
    btn.disabled = false;
    btn.textContent = "Apply metadata to selected rows";
    out.classList.remove("hidden");
    out.className = "result error";
    out.innerHTML = `<div class="result-title">Error</div><div class="result-detail">${esc(e.message || e)}</div>`;
    return;
  }
  setBfProgress("bf-step3-progress-wrap", false);
  btn.disabled = false;
  btn.textContent = "Apply metadata to selected rows";
  out.classList.remove("hidden");

  if (data.error) {
    out.className = "result error";
    out.innerHTML = `<div class="result-title">Error</div><div class="result-detail">${esc(data.error)}</div>`;
    return;
  }

  const s = data.summary || {};
  const results = data.results || [];
  const errLines = results
    .filter((r) => r.status === "error")
    .slice(0, 20)
    .map((r) => `• ${esc((r.filepath || "").split("/").pop())}: ${esc(r.reason || "error")}`);

  out.className = "result";
  out.innerHTML = `<div class="result-title">Batch finished</div>
    <div class="result-detail">OK: <strong>${s.ok ?? 0}</strong> · errors: <strong>${s.errors ?? 0}</strong> · skipped: <strong>${s.skipped ?? 0}</strong></div>
    ${errLines.length ? `<p class="hint" style="margin-top:0.5rem"><strong>Issues:</strong><br/>${errLines.join("<br/>")}</p>` : ""}`;
  saveBulkFixState();
}

document.getElementById("bf-choose-btn").addEventListener("click", openFolderModal);
document.getElementById("bf-default-btn").addEventListener("click", () => {
  resetDirToDefault();
});
document.getElementById("bf-modal-select").addEventListener("click", () => {
  if (folderModalPath) {
    $("#bf-dir").value = folderModalPath;
    closeFolderModal();
  }
});
document.getElementById("bf-modal-cancel").addEventListener("click", closeFolderModal);
document.getElementById("bf-folder-modal").addEventListener("click", (e) => {
  if (e.target && e.target.id === "bf-folder-modal") closeFolderModal();
});
document.getElementById("bf-load-batch-btn").addEventListener("click", loadBatch);
document.getElementById("bf-next-batch-btn").addEventListener("click", () => {
  const box = document.getElementById("bf-next-offset-box");
  const fromBox = box && !box.classList.contains("hidden") && box.dataset && box.dataset.nextOffset;
  if (fromBox) {
    $("#bf-offset").value = fromBox;
  } else {
    let lim = parseInt($("#bf-batch-size").value, 10);
    if (Number.isNaN(lim) || lim < 1) lim = 25;
    let off = parseInt($("#bf-offset").value, 10);
    if (Number.isNaN(off) || off < 0) off = 0;
    $("#bf-offset").value = String(off + lim);
  }
  loadBatch();
});
document.getElementById("bf-apply-next-offset")?.addEventListener("click", () => {
  const box = document.getElementById("bf-next-offset-box");
  const n = (box && box.dataset && box.dataset.nextOffset) || "";
  if (n === "") return;
  const el = document.getElementById("bf-offset");
  if (el) el.value = n;
});
document.getElementById("bf-fetch-matches-btn").addEventListener("click", fetchMatches);
document.getElementById("bf-apply-btn").addEventListener("click", applySelected);

["bf-dir", "bf-recursive", "bf-batch-size", "bf-offset", "bf-rename"].forEach((id) => {
  const el = document.getElementById(id);
  if (!el) return;
  el.addEventListener(id === "bf-recursive" || id === "bf-rename" ? "change" : "input", scheduleSaveBulkFixState);
});

initBulkFixPage();
