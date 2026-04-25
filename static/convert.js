const $ = (sel) => document.querySelector(sel);

let selectedWav = null;
let folderModalPath = "";
/** Which field the folder modal writes to: "convert-dir" | "convert-bulk-root" | "convert-bulk-target-dir" */
let folderModalFieldId = "convert-dir";
const BULK_TARGET_LS = "djmm.convertBulkTargetDir";
let settingsDestinationResolved = "";
let settingsDestinationDisplay = "";
let lastBulkScanCount = 0;

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
  updateBulkRunEnabled();
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

  let msg;
  if (limited) {
    msg = `Convert up to ${perRun} WAV file(s) in sorted order, starting at offset ${off}?\n\n${root}\n\n${
      lastBulkScanCount
        ? `Last scan: ${lastBulkScanCount} WAV file(s) total.`
        : "Scan first to see how many files exist."
    }\n\nYou can run again with a higher offset (use “Next offset”) until done.`;
  } else {
    const n = lastBulkScanCount || 0;
    if (n > 50) {
      msg = `Convert ALL ${n} WAV file(s) in one go?\n\n${root}\n\nThis is a long, heavy run. For large libraries, use “Limit each run to a batch” instead.`;
    } else {
      msg = lastBulkScanCount
        ? `Run conversion on this tree?\n\n${root}\n\n(last scan: ${lastBulkScanCount} WAV file(s))`
        : `Run conversion for every .wav under\n\n${root}\n\n(Scan first to count.)`;
    }
  }
  if (!window.confirm(msg)) return;

  const out = document.getElementById("convert-bulk-result");
  out.classList.add("hidden");
  const btn = document.getElementById("convert-bulk-run-btn");
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Converting…';
  const rec = document.getElementById("convert-bulk-recursive")?.checked !== false;
  const sk = document.getElementById("convert-bulk-skip")?.checked !== false;
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
  const resp = await fetch("/api/convert-wav-bulk", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await resp.json();
  out.classList.remove("hidden");
  if (data.error) {
    out.className = "result error";
    out.innerHTML = `<div class="result-title">Error</div><div class="result-detail">${data.error}</div>`;
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
      const bf = new URL("/bulk-fix", window.location.origin);
      bf.searchParams.set("dir", data.target_dir);
      bulkFixCta = `<p style="margin-top:0.6rem" class="field-row">
          <a class="btn btn-secondary" href="${bf.href}">Open Bulk fix for this folder</a>
          <span class="hint" style="margin:0 0.35rem 0 0.5rem">Match Discogs/Apple metadata in small batches; same path is pre-filled.</span>
        </p>`;
    }
    out.innerHTML = `<div class="result-title">Run finished</div><div class="result-detail">${parts.join(" · ")}</div>${rangeNote}${bulkFixCta}${errBlock}`;
  }
  btn.disabled = false;
  btn.textContent = "Run conversion";
  updateBulkRunEnabled();
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
    }
  }
  updateBulkRunEnabled();
});
document.getElementById("convert-modal-cancel").addEventListener("click", closeFolderModal);
document.getElementById("convert-folder-modal").addEventListener("click", (e) => {
  if (e.target && e.target.id === "convert-folder-modal") closeFolderModal();
});
document.getElementById("convert-run-btn").addEventListener("click", runConvert);
document.getElementById("convert-bulk-scan-btn")?.addEventListener("click", runBulkScan);
document.getElementById("convert-bulk-run-btn")?.addEventListener("click", runBulkConvert);
document.getElementById("convert-bulk-limited")?.addEventListener("change", syncConvertBulkBatchFields);
document.getElementById("convert-bulk-next-off-btn")?.addEventListener("click", () => {
  let per = parseInt(document.getElementById("convert-bulk-limit")?.value || "25", 10);
  if (Number.isNaN(per) || per < 1) per = 25;
  let off = parseInt(document.getElementById("convert-bulk-offset")?.value || "0", 10);
  if (Number.isNaN(off) || off < 0) off = 0;
  document.getElementById("convert-bulk-offset").value = String(off + per);
});
document.getElementById("convert-bulk-root")?.addEventListener("input", updateBulkRunEnabled);
document.getElementById("convert-bulk-root")?.addEventListener("keydown", (e) => {
  if (e.key === "Enter") runBulkScan();
});
document.getElementById("convert-bulk-target-dir")?.addEventListener("input", updateBulkRunEnabled);
document.getElementById("convert-bulk-target-dir")?.addEventListener("keydown", (e) => {
  if (e.key === "Enter") updateBulkRunEnabled();
});
document.querySelectorAll('input[name="convert-bulk-output"]').forEach((r) => {
  r.addEventListener("change", () => {
    syncBulkTargetRow();
    updateBulkRunEnabled();
  });
});
loadSettingsHints().then(async () => {
  try {
    const saved = localStorage.getItem(BULK_TARGET_LS);
    const ti = document.getElementById("convert-bulk-target-dir");
    if (saved && saved.trim() && ti) ti.value = saved.trim();
  } catch (_) {
    /* ignore */
  }
  syncConvertBulkBatchFields();
  syncBulkTargetRow();
  if ($("#convert-dir").value.trim()) {
    await browseWav();
  } else {
    $("#convert-file-list").innerHTML =
      '<div class="status">Type a folder path and click Browse, or use <strong>Default</strong> / <strong>Choose folder…</strong></div>';
  }
  updateBulkRunEnabled();
});
