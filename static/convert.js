const $ = (sel) => document.querySelector(sel);

function initConvertRollups() {
  function wire(btn, panel) {
    if (!btn || !panel) return;
    btn.addEventListener("click", () => {
      const open = btn.getAttribute("aria-expanded") === "true";
      const next = !open;
      btn.setAttribute("aria-expanded", next ? "true" : "false");
      panel.classList.toggle("convert-rollup-panel--hidden", !next);
    });
  }
  wire(document.getElementById("convert-toggle-single"), document.getElementById("convert-single-panel"));
  wire(document.getElementById("convert-toggle-bulk"), document.getElementById("convert-bulk-panel"));
}

function initConvertHelpTips() {
  document.querySelectorAll(".help-tip").forEach((wrap) => {
    const btn = wrap.querySelector(".help-tip-btn");
    if (!btn) return;
    btn.setAttribute("aria-expanded", "false");
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const wasOpen = wrap.classList.contains("help-tip--open");
      document.querySelectorAll(".help-tip--open").forEach((w) => {
        w.classList.remove("help-tip--open");
        const b = w.querySelector(".help-tip-btn");
        if (b) b.setAttribute("aria-expanded", "false");
      });
      if (!wasOpen) {
        wrap.classList.add("help-tip--open");
        btn.setAttribute("aria-expanded", "true");
      }
    });
    wrap.addEventListener("click", (e) => e.stopPropagation());
  });
  document.addEventListener("click", () => {
    document.querySelectorAll(".help-tip--open").forEach((w) => {
      w.classList.remove("help-tip--open");
      const b = w.querySelector(".help-tip-btn");
      if (b) b.setAttribute("aria-expanded", "false");
    });
  });
}

let selectedWav = null;
let folderModalPath = "";
/** Which field the folder modal writes to: "convert-dir" | "convert-bulk-root" | "convert-bulk-target-dir" */
let folderModalFieldId = "convert-dir";
const BULK_TARGET_LS = "djmm.convertBulkTargetDir";
/** Per resolved root: saved batch position after a successful limited bulk convert */
const BULK_WAV_PROGRESS_LS = "djmm.bulkWavProgressByRoot";
let settingsDestinationResolved = "";
let settingsDestinationDisplay = "";
let lastBulkScanCount = 0;
let bulkWavRestoreTimer = null;
const CONVERT_BULK_UI_LS = "djmm.convertBulkUi";
let convertBulkSaveTimer = null;

function getOutputMode() {
  return document.querySelector('input[name="convert-output"]:checked')?.value || "same";
}

function getBulkOutputMode() {
  return document.querySelector('input[name="convert-bulk-output"]:checked')?.value || "same";
}

function syncBulkTargetRow() {
  const custom = getBulkOutputMode() === "custom";
  const wrap = document.getElementById("convert-bulk-target-wrap");
  if (wrap) wrap.classList.toggle("hidden", !custom);
}

function getBulkTargetDir() {
  return document.getElementById("convert-bulk-target-dir")?.value.trim() || "";
}

function isConvertBulkBatchLimited() {
  return document.getElementById("convert-bulk-limited")?.checked !== false;
}

function syncConvertBulkBatchFields() {
  const on = isConvertBulkBatchLimited();
  const wrap = document.getElementById("convert-bulk-batch-fields");
  if (wrap) wrap.classList.toggle("hidden", !on);
}

function saveConvertBulkUi() {
  try {
    const out = document.getElementById("convert-bulk-result");
    const st = document.getElementById("convert-bulk-scan-status");
    const nextBox = document.getElementById("convert-bulk-next-box");
    const o = getBulkOutputMode();
    localStorage.setItem(
      CONVERT_BULK_UI_LS,
      JSON.stringify({
        v: 1,
        bulkRoot: document.getElementById("convert-bulk-root")?.value ?? "",
        recursive: document.getElementById("convert-bulk-recursive")?.checked ?? true,
        skipFlac: document.getElementById("convert-bulk-skip")?.checked ?? true,
        output: o,
        targetDir: getBulkTargetDir(),
        limited: isConvertBulkBatchLimited(),
        limit: document.getElementById("convert-bulk-limit")?.value ?? "25",
        offset: document.getElementById("convert-bulk-offset")?.value ?? "0",
        lastBulkScanCount,
        scanStatus: st?.textContent ?? "",
        scanStatusHidden: st?.classList.contains("hidden") ?? true,
        resultHtml: out && !out.classList.contains("hidden") ? out.innerHTML : "",
        resultClass: out?.className ?? "result hidden",
        resultHidden: out?.classList.contains("hidden") ?? true,
        nextBoxHidden: nextBox?.classList.contains("hidden") ?? true,
        nextOffset: nextBox?.dataset?.nextOffset ?? "",
      }),
    );
  } catch (_) {
    /* ignore */
  }
}

function scheduleSaveConvertBulkUi() {
  if (convertBulkSaveTimer) clearTimeout(convertBulkSaveTimer);
  convertBulkSaveTimer = setTimeout(() => {
    convertBulkSaveTimer = null;
    saveConvertBulkUi();
  }, 400);
}

function restoreConvertBulkUi() {
  try {
    const raw = localStorage.getItem(CONVERT_BULK_UI_LS);
    if (!raw) return;
    const s = JSON.parse(raw);
    if (!s || s.v !== 1) return;
    const r = document.getElementById("convert-bulk-root");
    if (r && s.bulkRoot != null) r.value = s.bulkRoot;
    const rec = document.getElementById("convert-bulk-recursive");
    if (rec) rec.checked = s.recursive !== false;
    const sk = document.getElementById("convert-bulk-skip");
    if (sk) sk.checked = s.skipFlac !== false;
    const outMode = s.output;
    const rid =
      outMode === "same"
        ? "convert-bulk-out-same"
        : outMode === "destination"
          ? "convert-bulk-out-dest"
          : outMode === "custom"
            ? "convert-bulk-out-custom"
            : null;
    if (rid) {
      const radio = document.getElementById(rid);
      if (radio) radio.checked = true;
    }
    if (outMode === "custom" && s.targetDir != null) {
      const ti = document.getElementById("convert-bulk-target-dir");
      if (ti) ti.value = s.targetDir;
    }
    syncBulkTargetRow();
    const limC = document.getElementById("convert-bulk-limited");
    if (limC) limC.checked = s.limited !== false;
    syncConvertBulkBatchFields();
    const limIn = document.getElementById("convert-bulk-limit");
    const offIn = document.getElementById("convert-bulk-offset");
    if (limIn && s.limit != null) limIn.value = String(s.limit);
    if (offIn && s.offset != null) offIn.value = String(s.offset);
    if (s.lastBulkScanCount != null) lastBulkScanCount = s.lastBulkScanCount;
    const st = document.getElementById("convert-bulk-scan-status");
    if (st) {
      if (s.scanStatus != null && !s.scanStatusHidden) {
        st.textContent = s.scanStatus;
        st.classList.remove("hidden");
      }
    }
    const out = document.getElementById("convert-bulk-result");
    if (out && s.resultHtml && !s.resultHidden) {
      out.innerHTML = s.resultHtml;
      out.className = s.resultClass || "result";
      out.classList.remove("hidden");
    }
    const nextBox = document.getElementById("convert-bulk-next-box");
    if (nextBox && s.nextOffset) {
      nextBox.dataset.nextOffset = String(s.nextOffset);
      if (!s.nextBoxHidden) nextBox.classList.remove("hidden");
    }
    updateBulkRunEnabled();
  } catch (_) {
    /* ignore */
  }
}

function setConvertBulkProgress(visible, label) {
  const wrap = document.getElementById("convert-bulk-progress-wrap");
  const lab = document.getElementById("convert-bulk-progress-label");
  if (!wrap) return;
  wrap.classList.toggle("hidden", !visible);
  wrap.setAttribute("aria-busy", visible ? "true" : "false");
  if (lab && label) lab.textContent = label;
}

function updateConvertNextOffsetFromResponse(data) {
  const box = document.getElementById("convert-bulk-next-box");
  if (!box) return;
  const b = data.batch || {};
  if (data.error || b.total_wavs == null || typeof b.candidates_in_batch !== "number") {
    box.classList.add("hidden");
    return;
  }
  if (b.candidates_in_batch === 0) {
    box.classList.add("hidden");
    return;
  }
  const nextOff = b.offset + b.candidates_in_batch;
  const total = b.total_wavs;
  const v0 = document.getElementById("convert-next-offset-0");
  const v1 = document.getElementById("convert-next-1-based");
  const det = document.getElementById("convert-next-offset-detail");
  if (v0) v0.textContent = String(nextOff);
  if (v1) v1.textContent = String(nextOff + 1);
  if (det) {
    if (nextOff < total) {
      det.textContent = `${total} WAV(s) in the sorted list. Next run: set Offset to ${nextOff} — that starts at the ${nextOff + 1}${nth(nextOff + 1)} file when counting 1, 2, 3…`;
    } else {
      det.textContent = `End of the list (${total} WAV path(s)). You are done unless you add files.`;
    }
  }
  box.dataset.nextOffset = String(nextOff);
  box.classList.remove("hidden");
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

function getBulkWavProgressMap() {
  try {
    const raw = localStorage.getItem(BULK_WAV_PROGRESS_LS);
    if (!raw) return {};
    const o = JSON.parse(raw);
    return o && typeof o === "object" && !Array.isArray(o) ? o : {};
  } catch (_) {
    return {};
  }
}

function setBulkWavProgressMap(map) {
  try {
    localStorage.setItem(BULK_WAV_PROGRESS_LS, JSON.stringify(map));
  } catch (_) {
    /* ignore */
  }
}

function persistBulkWavProgressFromConvertResponse(data, uiLimited) {
  if (!data || data.error || !data.root) return;
  if (!uiLimited) return;
  const b = data.batch || {};
  if (b.limit == null) return;
  if (typeof b.offset !== "number" || typeof b.candidates_in_batch !== "number") return;
  if (b.candidates_in_batch < 1) return;
  const nextOffset = b.offset + b.candidates_in_batch;
  const rec = document.getElementById("convert-bulk-recursive")?.checked !== false;
  const sk = document.getElementById("convert-bulk-skip")?.checked !== false;
  const outMode = getBulkOutputMode();
  const entry = {
    nextOffset,
    limit: b.limit,
    recursive: rec,
    output: outMode,
    targetDir: outMode === "custom" ? getBulkTargetDir() : "",
    skipFlac: sk,
    limited: true,
    updatedAt: new Date().toISOString(),
  };
  const map = getBulkWavProgressMap();
  map[String(data.root)] = entry;
  setBulkWavProgressMap(map);
}

function clearBulkWavProgressForRoot(resolvedRoot) {
  if (!resolvedRoot) return;
  const map = getBulkWavProgressMap();
  delete map[String(resolvedRoot)];
  setBulkWavProgressMap(map);
}

async function resolveConvertBulkRootPath(raw) {
  const t = (raw || "").trim();
  if (!t) return null;
  const resp = await fetch(`/api/browse-folders?path=${encodeURIComponent(t)}`);
  const data = await resp.json();
  if (data.error) return null;
  return data.path || null;
}

/**
 * Apply saved batch options for a resolved root. Returns a short status suffix or "".
 */
function tryApplyBulkWavProgressForResolvedRoot(resolvedRoot) {
  if (!resolvedRoot) return "";
  const entry = getBulkWavProgressMap()[String(resolvedRoot)];
  if (!entry || !entry.limited) return "";
  const recNow = document.getElementById("convert-bulk-recursive")?.checked !== false;
  if (entry.recursive !== recNow) {
    return ` Saved batch position on disk uses “subfolders” ${entry.recursive ? "on" : "off"} — turn it ${entry.recursive ? "on" : "off"} to restore offset ${entry.nextOffset}, or clear saved progress.`;
  }
  const limEl = document.getElementById("convert-bulk-limited");
  if (limEl) limEl.checked = true;
  syncConvertBulkBatchFields();
  const offEl = document.getElementById("convert-bulk-offset");
  const limNum = document.getElementById("convert-bulk-limit");
  if (offEl) offEl.value = String(entry.nextOffset);
  if (limNum) limNum.value = String(entry.limit);
  const skipEl = document.getElementById("convert-bulk-skip");
  if (skipEl) skipEl.checked = entry.skipFlac !== false;
  const out = entry.output;
  const rid =
    out === "same"
      ? "convert-bulk-out-same"
      : out === "destination"
        ? "convert-bulk-out-dest"
        : out === "custom"
          ? "convert-bulk-out-custom"
          : null;
  if (rid) {
    const radio = document.getElementById(rid);
    if (radio) radio.checked = true;
  }
  if (out === "custom") {
    const ti = document.getElementById("convert-bulk-target-dir");
    if (ti && entry.targetDir) ti.value = entry.targetDir;
  }
  syncBulkTargetRow();
  updateBulkRunEnabled();
  const when = entry.updatedAt ? new Date(entry.updatedAt).toLocaleString() : "";
  return when
    ? ` Restored saved batch position: offset ${entry.nextOffset}, ${entry.limit} per run (saved ${when}).`
    : ` Restored saved batch position: offset ${entry.nextOffset}, ${entry.limit} per run.`;
}

function escHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function buildBulkConvertConfirmHtml(limited, off, perRun, root) {
  const pathBlock = `<div class="bulk-confirm-path mono">${escHtml(root)}</div>`;
  if (limited) {
    const scanHint = lastBulkScanCount
      ? `Last scan: <strong>${lastBulkScanCount}</strong> WAV file(s) total.`
      : "You have not scanned this session — the server still uses the same sorted file list.";
    return (
      pathBlock +
      `<p style="margin:0 0 0.35rem">Convert up to <strong>${perRun}</strong> WAV file(s) in <strong>sorted</strong> order, starting at offset <strong>${off}</strong> (0-based).</p>` +
      `<p class="hint" style="margin:0 0 0.5rem">${scanHint}</p>` +
      `<p class="hint" style="margin:0">After this run, raise the offset or use <strong>Next offset</strong> until the tree is done.</p>`
    );
  }
  const n = lastBulkScanCount || 0;
  if (n > 50) {
    return (
      pathBlock +
      `<p style="margin:0 0 0.35rem">Convert <strong>all ${n}</strong> WAV file(s) in <strong>one</strong> run. This may take a long time and load the machine heavily.</p>` +
      `<p class="hint" style="margin:0">For large libraries, use <strong>Limit each run to a batch</strong> instead.</p>`
    );
  }
  if (lastBulkScanCount) {
    return (
      pathBlock +
      `<p style="margin:0 0 0.35rem">Convert every <code>.wav</code> under this tree (last scan: <strong>${lastBulkScanCount}</strong> file(s)).</p>` +
      `<p class="hint" style="margin:0">This unlimited run processes the full sorted list in one go.</p>`
    );
  }
  return (
    pathBlock +
    `<p style="margin:0 0 0.35rem">Convert every <code>.wav</code> under this tree.</p>` +
    `<p class="hint" style="margin:0"><strong>Scan first</strong> to see how many files will be processed.</p>`
  );
}

let bulkConvertConfirmHandler = null;

function onBulkConfirmModalKeydown(e) {
  if (e.key === "Escape") closeBulkConvertConfirmModal();
}

function closeBulkConvertConfirmModal() {
  const ov = document.getElementById("convert-bulk-confirm-modal");
  if (ov) ov.classList.add("hidden");
  document.removeEventListener("keydown", onBulkConfirmModalKeydown);
  bulkConvertConfirmHandler = null;
}

function openBulkConvertConfirmModal(title, innerHtml, onConfirm) {
  const ov = document.getElementById("convert-bulk-confirm-modal");
  const tEl = document.getElementById("convert-bulk-confirm-title");
  const bEl = document.getElementById("convert-bulk-confirm-body");
  if (tEl) tEl.textContent = title;
  if (bEl) bEl.innerHTML = innerHtml;
  bulkConvertConfirmHandler = onConfirm;
  ov?.classList.remove("hidden");
  document.addEventListener("keydown", onBulkConfirmModalKeydown);
  document.getElementById("convert-bulk-confirm-ok")?.focus();
}

async function performBulkConvert(root, limited, off, perRun, outMode, rec, sk) {
  document.getElementById("convert-bulk-next-box")?.classList.add("hidden");
  const out = document.getElementById("convert-bulk-result");
  out.classList.add("hidden");
  const btn = document.getElementById("convert-bulk-run-btn");
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Converting…';
  setConvertBulkProgress(true, "Converting WAVs to FLAC (server is processing the batch)…");
  const body = {
    root_dir: root,
    output: outMode,
    recursive: rec,
    skip_if_flac_exists: sk,
  };
  if (outMode === "custom") {
    body.target_dir = getBulkTargetDir();
  }
  if (limited) {
    body.offset = off;
    body.limit = perRun;
  }
  let data;
  try {
    const resp = await fetch("/api/convert-wav-bulk", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    data = await resp.json();
  } catch (e) {
    setConvertBulkProgress(false);
    out.classList.remove("hidden");
    out.className = "result error";
    out.innerHTML = `<div class="result-title">Error</div><div class="result-detail">${escHtml(String(e.message || e))}</div>`;
    btn.disabled = false;
    btn.textContent = "Run conversion";
    updateBulkRunEnabled();
    return;
  }
  setConvertBulkProgress(false);
  out.classList.remove("hidden");
  if (data.error) {
    out.className = "result error";
    out.innerHTML = `<div class="result-title">Error</div><div class="result-detail">${data.error}</div>`;
    document.getElementById("convert-bulk-next-box")?.classList.add("hidden");
  } else {
    out.className = "result";
    const s = data.summary || {};
    const parts = [
      `Converted: <strong>${s.converted ?? 0}</strong>`,
      `Skipped (FLAC already there): <strong>${s.skipped ?? 0}</strong>`,
      `Errors: <strong>${s.errors ?? 0}</strong>`,
    ];
    let errBlock = "";
    if (data.errors && data.errors.length) {
      const lines = data.errors
        .slice(0, 30)
        .map((e) => `• <span class="mono">${(e.source || "").split("/").pop()}</span>: ${(e.error || "").replace(/</g, "&lt;")}`)
        .join("<br>");
      errBlock = `<p class="hint" style="margin-top:0.5rem"><strong>First issue(s):</strong><br/>${lines}</p>`;
      if (data.errors.length > 30) {
        errBlock += `<p class="hint">… and ${data.errors.length - 30} more (see server log if needed).</p>`;
      }
    }
    const b = data.batch || {};
    let rangeNote = "";
    if (b.total_wavs != null && typeof b.candidates_in_batch === "number") {
      if (b.candidates_in_batch === 0) {
        rangeNote = `<p class="hint" style="margin-top:0.4rem">No WAV paths in this offset/limit window (${b.total_wavs} total). Raise the offset or clear the range — or you may be finished.</p>`;
      } else {
        const fromN = b.offset + 1;
        const toN = b.offset + b.candidates_in_batch;
        rangeNote = `<p class="hint" style="margin-top:0.4rem">Sorted list: this run covered file <strong>${fromN}–${toN}</strong> of <strong>${b.total_wavs}</strong> WAV path(s) ${
          limited && b.limit != null ? `(batch size ${b.limit})` : ""
        }.</p>`;
      }
    }
    let bulkFixCta = "";
    if (outMode === "custom" && data.target_dir) {
      try {
        const paths = data.batch_flac_paths;
        if (Array.isArray(paths) && paths.length) {
          localStorage.setItem(
            "djmm.bulkFixHandoff",
            JSON.stringify({
              v: 1,
              targetDir: data.target_dir,
              paths,
            }),
          );
        } else {
          localStorage.removeItem("djmm.bulkFixHandoff");
        }
      } catch (_) {
        /* ignore */
      }
      const bf = new URL("/bulk-fix", window.location.origin);
      bf.searchParams.set("dir", data.target_dir);
      bulkFixCta = `<p style="margin-top:0.6rem" class="field-row">
          <a class="btn btn-secondary" href="${escHtml(bf.href)}">Open Bulk Fix for this folder</a>
          <span class="hint" style="margin:0 0.35rem 0 0.5rem">Opens Bulk Fix and loads this run’s FLACs in <strong>conversion order</strong> (not alphabetical folder order after flat rename).</span>
        </p>`;
    }
    out.innerHTML = `<div class="result-title">Run finished</div><div class="result-detail">${parts.join(" · ")}</div>${rangeNote}${bulkFixCta}${errBlock}`;
    updateConvertNextOffsetFromResponse(data);
    persistBulkWavProgressFromConvertResponse(data, limited);
  }
  btn.disabled = false;
  btn.textContent = "Run conversion";
  updateBulkRunEnabled();
  saveConvertBulkUi();
}

function scheduleTryApplyBulkWavProgressFromInput() {
  if (bulkWavRestoreTimer) clearTimeout(bulkWavRestoreTimer);
  bulkWavRestoreTimer = setTimeout(async () => {
    bulkWavRestoreTimer = null;
    const raw = document.getElementById("convert-bulk-root")?.value.trim();
    if (!raw) return;
    const resolved = await resolveConvertBulkRootPath(raw);
    if (!resolved) return;
    const suffix = tryApplyBulkWavProgressForResolvedRoot(resolved);
    if (!suffix) return;
    const st = document.getElementById("convert-bulk-scan-status");
    if (!st) return;
    if (st.textContent.includes("Scanning")) return;
    st.classList.remove("hidden");
    const base = st.textContent.trim();
    st.textContent = base ? `${base}${suffix}` : suffix.trim();
    scheduleSaveConvertBulkUi();
  }, 450);
}

async function loadSettingsHints() {
  const resp = await fetch("/api/settings");
  const cfg = await resp.json();
  const dest = (cfg.destination_dir || "").trim();
  if (dest) {
    const resolved = cfg.destination_dir_resolved || dest;
    settingsDestinationDisplay = dest;
    settingsDestinationResolved = resolved;
    $("#convert-dest-hint").textContent =
      `Settings destination: ${dest}  →  ${resolved}`;
  } else {
    settingsDestinationDisplay = "";
    settingsDestinationResolved = "";
    $("#convert-dest-hint").textContent =
      "No destination folder in Settings — use “Same folder as the WAV” or set Settings → destination folder.";
  }
  if (!selectedWav && !$("#convert-dir").value.trim()) {
    $("#convert-dir").value = dest;
  }
}

function closeFolderModal() {
  const el = document.getElementById("convert-folder-modal");
  if (el) el.classList.add("hidden");
  document.removeEventListener("keydown", onFolderModalKeydown);
}

function onFolderModalKeydown(e) {
  if (e.key === "Escape") closeFolderModal();
}

async function openFolderModal(fieldId = "convert-dir") {
  folderModalFieldId = fieldId;
  const inp = document.getElementById(fieldId);
  let start = (inp && inp.value.trim()) || "";
  if (!start) {
    const resp = await fetch("/api/settings");
    const cfg = await resp.json();
    if (fieldId === "convert-bulk-root" && (cfg.source_dir || "").trim()) {
      start = (cfg.source_dir || "").trim();
    } else {
      start = (cfg.destination_dir || "").trim() || "~";
    }
  }
  document.getElementById("convert-folder-modal").classList.remove("hidden");
  document.addEventListener("keydown", onFolderModalKeydown);
  await loadFolderInModal(start);
}

async function loadFolderInModal(path) {
  const listEl = $("#convert-modal-dir-list");
  const pathEl = $("#convert-modal-path");
  const upBtn = $("#convert-modal-up");
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

async function resetDirToDefault() {
  const resp = await fetch("/api/settings");
  const cfg = await resp.json();
  const dest = (cfg.destination_dir || "").trim();
  $("#convert-dir").value = dest;
  if (dest) {
    await browseWav();
  } else {
    $("#convert-file-list").innerHTML = '<div class="status">Set a destination in Settings, or type a path and use Browse.</div>';
  }
}

async function browseWav() {
  const dir = $("#convert-dir").value.trim();
  if (!dir) {
    $("#convert-file-list").innerHTML = '<div class="status">Enter a folder path, or use Default / Choose folder.</div>';
    return;
  }
  const resp = await fetch(`/api/browse-wav?dir=${encodeURIComponent(dir)}`);
  const data = await resp.json();
  if (data.error) {
    $("#convert-file-list").innerHTML = `<div class="status">${data.error}</div>`;
    return;
  }
  $("#convert-dir").value = data.directory;
  if (!data.files || data.files.length === 0) {
    $("#convert-file-list").innerHTML = '<div class="status">No .wav files in this folder</div>';
    return;
  }
  const wavPaths = data.files.map((f) => f.path);
  const esc = (s) =>
    String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  $("#convert-file-list").innerHTML = data.files
    .map(
      (f, i) =>
        `<div class="file-item" data-idx="${i}">
          <span class="file-name">${esc(f.name)}</span>
          <span class="file-size">${f.size_mb} MB</span>
        </div>`
    )
    .join("");

  $("#convert-file-list").querySelectorAll(".file-item").forEach((el) => {
    el.addEventListener("click", () => {
      $("#convert-file-list").querySelectorAll(".file-item").forEach((e) => e.classList.remove("selected"));
      el.classList.add("selected");
      const i = parseInt(el.dataset.idx, 10);
      selectedWav = !Number.isNaN(i) && wavPaths[i] ? wavPaths[i] : null;
      const hint = $("#convert-selected");
      hint.classList.remove("hidden");
      hint.innerHTML = `<span><strong>Selected:</strong> ${selectedWav.split("/").pop()}</span>`;
      $("#convert-run-btn").disabled = false;
      $("#convert-result").classList.add("hidden");
    });
  });
}

async function runConvert() {
  if (!selectedWav) return;
  if (getOutputMode() === "destination" && !settingsDestinationResolved) {
    $("#convert-result").className = "result error";
    $("#convert-result").classList.remove("hidden");
    $("#convert-result").innerHTML =
      "<div class=\"result-title\">Cannot use destination</div><div class=\"result-detail\">Set a destination folder in <a href=\"/settings\">Settings</a> first, or pick “Same folder as the WAV”.</div>";
    return;
  }

  const btn = $("#convert-run-btn");
  const result = $("#convert-result");
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Converting…';
  result.classList.add("hidden");

  const resp = await fetch("/api/convert-wav-to-flac", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      filepath: selectedWav,
      output: getOutputMode(),
    }),
  });
  const data = await resp.json();
  result.classList.remove("hidden");
  if (data.error) {
    result.className = "result error";
    result.innerHTML = `<div class="result-title">Error</div><div class="result-detail">${data.error}</div>`;
  } else {
    result.className = "result";
    const parts = [
      `Wrote <strong>${data.output_path || ""}</strong>`,
      data.size_mb != null ? `${data.size_mb} MB` : "",
      "Source WAV was not modified.",
    ].filter(Boolean);
    const fixUrl = new URL("/fix", window.location.origin);
    if (data.output_path) {
      fixUrl.searchParams.set("file", data.output_path);
    }
    const openFix = data.output_path
      ? `<div style="margin-top:0.75rem" class="field-row">
           <a class="btn btn-secondary" href="${fixUrl.href}">Open in Fix Metadata</a>
           <p class="hint" style="margin:0.35rem 0 0">Opens the same FLAC here: fills title/artist from <code>Slot - BPM - Artist - Title</code> when tags are empty, and runs <strong>Discogs + Apple</strong> search.</p>
         </div>`
      : "";
    const tagNote = data.tag_error
      ? `<p class="hint" style="margin-top:0.5rem">Tag embed: ${String(data.tag_error).replace(/</g, "&lt;")} — you can set tags in Fix Metadata.</p>`
      : "";
    result.innerHTML = `<div class="result-title">Done</div><div class="result-detail">${parts.join(" · ")}</div>${tagNote}${openFix}`;
  }
  btn.disabled = false;
  btn.textContent = "Convert to FLAC";
}

function updateBulkRunEnabled() {
  const on = document.getElementById("convert-bulk-root")?.value.trim();
  const needTarget = getBulkOutputMode() === "custom" && !getBulkTargetDir();
  const btn = document.getElementById("convert-bulk-run-btn");
  if (btn) btn.disabled = !on || needTarget;
}

async function runBulkScan() {
  const root = document.getElementById("convert-bulk-root")?.value.trim();
  const st = document.getElementById("convert-bulk-scan-status");
  st.classList.remove("hidden");
  if (!root) {
    st.textContent = "Set a root folder first.";
    lastBulkScanCount = 0;
    return;
  }
  st.textContent = "Scanning…";
  const rec = document.getElementById("convert-bulk-recursive")?.checked !== false;
  const u = new URL("/api/scan-wav-bulk", window.location.origin);
  u.searchParams.set("path", root);
  u.searchParams.set("recursive", rec ? "1" : "0");
  const resp = await fetch(u);
  const data = await resp.json();
  if (data.error) {
    st.textContent = data.error;
    lastBulkScanCount = 0;
    return;
  }
  lastBulkScanCount = data.count;
  st.textContent = `Found ${data.count} WAV file(s) under ${data.root}`;
  const restored = tryApplyBulkWavProgressForResolvedRoot(data.root);
  if (restored) st.textContent += restored;
  updateBulkRunEnabled();
  saveConvertBulkUi();
}

async function runBulkConvert() {
  const root = document.getElementById("convert-bulk-root")?.value.trim();
  if (!root) return;
  const outMode = getBulkOutputMode();
  if (outMode === "destination" && !settingsDestinationResolved) {
    const el = document.getElementById("convert-bulk-result");
    el.className = "result error";
    el.classList.remove("hidden");
    el.innerHTML = "<div class=\"result-title\">Cannot use destination</div><div class=\"result-detail\">Set a destination in <a href=\"/settings\">Settings</a> or use another output mode.</div>";
    return;
  }
  if (outMode === "custom") {
    const t = getBulkTargetDir();
    if (!t) {
      const el = document.getElementById("convert-bulk-result");
      el.className = "result error";
      el.classList.remove("hidden");
      el.innerHTML = "<div class=\"result-title\">Target folder</div><div class=\"result-detail\">Enter or choose a folder for converted FLACs (one flat library folder).</div>";
      return;
    }
    try {
      localStorage.setItem(BULK_TARGET_LS, t);
    } catch (_) {
      /* ignore */
    }
  }
  const limited = isConvertBulkBatchLimited();
  let off = parseInt(document.getElementById("convert-bulk-offset")?.value || "0", 10);
  if (Number.isNaN(off) || off < 0) off = 0;
  let perRun = parseInt(document.getElementById("convert-bulk-limit")?.value || "25", 10);
  if (Number.isNaN(perRun) || perRun < 1) perRun = 25;
  if (perRun > 500) perRun = 500;

  const confirmHtml = buildBulkConvertConfirmHtml(limited, off, perRun, root);
  openBulkConvertConfirmModal("Run bulk conversion?", confirmHtml, () => {
    const rec = document.getElementById("convert-bulk-recursive")?.checked !== false;
    const sk = document.getElementById("convert-bulk-skip")?.checked !== false;
    void performBulkConvert(root, limited, off, perRun, outMode, rec, sk);
  });
}

document.getElementById("convert-browse-btn").addEventListener("click", browseWav);
document.getElementById("convert-choose-folder-btn").addEventListener("click", () => openFolderModal("convert-dir"));
document.getElementById("convert-bulk-choose-btn").addEventListener("click", () => openFolderModal("convert-bulk-root"));
document.getElementById("convert-bulk-target-choose-btn")?.addEventListener("click", () => openFolderModal("convert-bulk-target-dir"));
document.getElementById("convert-default-dir-btn").addEventListener("click", resetDirToDefault);
document.getElementById("convert-dir").addEventListener("keydown", (e) => {
  if (e.key === "Enter") browseWav();
});
document.getElementById("convert-modal-select").addEventListener("click", () => {
  if (folderModalPath) {
    const el = document.getElementById(folderModalFieldId);
    if (el) el.value = folderModalPath;
    closeFolderModal();
    if (folderModalFieldId === "convert-dir") {
      browseWav();
    } else if (folderModalFieldId === "convert-bulk-root") {
      lastBulkScanCount = 0;
      const st = document.getElementById("convert-bulk-scan-status");
      if (st) {
        st.classList.add("hidden");
        st.textContent = "";
      }
      const suffix = tryApplyBulkWavProgressForResolvedRoot(folderModalPath);
      if (suffix && st) {
        st.classList.remove("hidden");
        st.textContent = suffix.trim();
      }
    }
  }
  updateBulkRunEnabled();
  scheduleSaveConvertBulkUi();
});
document.getElementById("convert-modal-cancel").addEventListener("click", closeFolderModal);
document.getElementById("convert-folder-modal").addEventListener("click", (e) => {
  if (e.target && e.target.id === "convert-folder-modal") closeFolderModal();
});
document.getElementById("convert-bulk-confirm-ok")?.addEventListener("click", () => {
  const fn = bulkConvertConfirmHandler;
  closeBulkConvertConfirmModal();
  if (fn) fn();
});
document.getElementById("convert-bulk-confirm-cancel")?.addEventListener("click", closeBulkConvertConfirmModal);
document.getElementById("convert-bulk-confirm-modal")?.addEventListener("click", (e) => {
  if (e.target && e.target.id === "convert-bulk-confirm-modal") closeBulkConvertConfirmModal();
});
document.getElementById("convert-run-btn").addEventListener("click", runConvert);
document.getElementById("convert-bulk-scan-btn")?.addEventListener("click", runBulkScan);
document.getElementById("convert-bulk-run-btn")?.addEventListener("click", runBulkConvert);
document.getElementById("convert-bulk-limited")?.addEventListener("change", syncConvertBulkBatchFields);
document.getElementById("convert-bulk-next-off-btn")?.addEventListener("click", () => {
  const box = document.getElementById("convert-bulk-next-box");
  const fromBox = box && !box.classList.contains("hidden") && box.dataset && box.dataset.nextOffset;
  if (fromBox) {
    document.getElementById("convert-bulk-offset").value = fromBox;
    return;
  }
  let per = parseInt(document.getElementById("convert-bulk-limit")?.value || "25", 10);
  if (Number.isNaN(per) || per < 1) per = 25;
  let off = parseInt(document.getElementById("convert-bulk-offset")?.value || "0", 10);
  if (Number.isNaN(off) || off < 0) off = 0;
  document.getElementById("convert-bulk-offset").value = String(off + per);
});
document.getElementById("convert-apply-next-offset")?.addEventListener("click", () => {
  const box = document.getElementById("convert-bulk-next-box");
  const n = (box && box.dataset && box.dataset.nextOffset) || "";
  if (n === "") return;
  const el = document.getElementById("convert-bulk-offset");
  if (el) el.value = n;
});
document.getElementById("convert-bulk-root")?.addEventListener("input", updateBulkRunEnabled);
document.getElementById("convert-bulk-root")?.addEventListener("blur", () => scheduleTryApplyBulkWavProgressFromInput());
document.getElementById("convert-bulk-root")?.addEventListener("keydown", (e) => {
  if (e.key === "Enter") runBulkScan();
});
document.getElementById("convert-bulk-clear-progress-btn")?.addEventListener("click", async () => {
  const raw = document.getElementById("convert-bulk-root")?.value.trim();
  const st = document.getElementById("convert-bulk-scan-status");
  if (!raw) {
    if (st) {
      st.classList.remove("hidden");
      st.textContent = "Set a root folder first.";
    }
    return;
  }
  const resolved = await resolveConvertBulkRootPath(raw);
  if (!resolved) {
    if (st) {
      st.classList.remove("hidden");
      st.textContent = "Could not resolve that path — fix the folder path and try again.";
    }
    return;
  }
  clearBulkWavProgressForRoot(resolved);
  if (st) {
    st.classList.remove("hidden");
    st.textContent = `Cleared saved batch progress for ${resolved}.`;
  }
});
document.getElementById("convert-bulk-target-dir")?.addEventListener("input", updateBulkRunEnabled);
document.getElementById("convert-bulk-target-dir")?.addEventListener("keydown", (e) => {
  if (e.key === "Enter") updateBulkRunEnabled();
});
document.querySelectorAll('input[name="convert-bulk-output"]').forEach((r) => {
  r.addEventListener("change", () => {
    syncBulkTargetRow();
    updateBulkRunEnabled();
    scheduleSaveConvertBulkUi();
  });
});
[
  "convert-bulk-root",
  "convert-bulk-recursive",
  "convert-bulk-skip",
  "convert-bulk-limited",
  "convert-bulk-limit",
  "convert-bulk-offset",
  "convert-bulk-target-dir",
].forEach((id) => {
  const el = document.getElementById(id);
  if (!el) return;
  const ev =
    id === "convert-bulk-recursive" || id === "convert-bulk-skip" || id === "convert-bulk-limited" ? "change" : "input";
  el.addEventListener(ev, scheduleSaveConvertBulkUi);
});
loadSettingsHints().then(async () => {
  initConvertRollups();
  initConvertHelpTips();
  try {
    const saved = localStorage.getItem(BULK_TARGET_LS);
    const ti = document.getElementById("convert-bulk-target-dir");
    if (saved && saved.trim() && ti) ti.value = saved.trim();
  } catch (_) {
    /* ignore */
  }
  restoreConvertBulkUi();
  syncConvertBulkBatchFields();
  syncBulkTargetRow();
  if ($("#convert-dir").value.trim()) {
    await browseWav();
  } else {
    $("#convert-file-list").innerHTML =
      '<div class="status">Expand <strong>Single file</strong> above, enter a folder path, then Browse — or Default / Choose folder…</div>';
  }
  updateBulkRunEnabled();
});
