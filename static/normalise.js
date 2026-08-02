const $ = (sel) => document.querySelector(sel);

let selectedFile = null;
let currentLoudnormParams = null;

function collectNormalisePageState() {
  return {
    v: 1,
    normDir: $("#norm-dir").value,
    normSuffix: $("#norm-suffix").value,
    selectedFile,
    normBulkDir: ($("#norm-bulk-dir") || {}).value || "",
    normBulkSuffix: ($("#norm-bulk-suffix") || {}).value || "_norm",
    normBulkRecursive: document.getElementById("norm-bulk-recursive")?.checked || false,
  };
}

function scheduleNormalisePageSave() {
  if (typeof djmmPageStateSchedule === "function") {
    djmmPageStateSchedule("normalise", collectNormalisePageState);
  }
}

function updateNormTargetLabels(cfg) {
  const lu = cfg.target_lufs != null ? cfg.target_lufs : -14;
  const tp = cfg.target_true_peak != null ? cfg.target_true_peak : -1;
  const el = $("#norm-target-label");
  if (el) el.textContent = `${lu} LUFS (${tp} dBTP peak)`;
  const fmt = $("#norm-format-hint");
  if (fmt && cfg.extract_profile_label) {
    fmt.textContent = cfg.extract_profile_label;
  }
  const btn = $("#norm-run-btn");
  if (btn) btn.textContent = `Normalise to ${lu} LUFS`;
}

async function loadSettings() {
  const resp = await fetch("/api/settings");
  const cfg = await resp.json();
  $("#norm-dir").value = cfg.destination_dir || "";
  updateNormTargetLabels(cfg);
}

async function browseAudio() {
  const dir = $("#norm-dir").value.trim();
  if (!dir) return;

  const resp = await fetch(`/api/browse-audio?dir=${encodeURIComponent(dir)}`);
  const data = await resp.json();

  if (data.error) {
    $("#norm-file-list").innerHTML = `<div class="status">${data.error}</div>`;
    scheduleNormalisePageSave();
    return;
  }

  $("#norm-dir").value = data.directory;

  const audio = data.files || [];
  if (audio.length === 0) {
    $("#norm-file-list").innerHTML = '<div class="status">No supported audio files in this folder</div>';
    scheduleNormalisePageSave();
    return;
  }

  $("#norm-file-list").innerHTML = audio
    .map(
      (f) =>
        `<div class="file-item" data-path="${f.path}">
          <span class="file-name">${f.name}</span>
          <span class="file-size">${f.size_mb} MB</span>
        </div>`
    )
    .join("");

  $("#norm-file-list").querySelectorAll(".file-item").forEach((el) => {
    el.addEventListener("click", () => selectFile(el));
  });
  if (DJMM.initFileListSearch) {
    DJMM.initFileListSearch({ listId: "norm-file-list", onSelect: selectFile, pageClass: "page-normalise" });
  }
  wireNormFileListArrowNav();
  scheduleNormalisePageSave();
}

async function selectFile(el) {
  $("#norm-file-list").querySelectorAll(".file-item").forEach((e) => e.classList.remove("selected"));
  el.classList.add("selected");
  selectedFile = el.dataset.path;
  currentLoudnormParams = null;
  $("#norm-run-btn").disabled = true;
  $("#norm-result").classList.add("hidden");

  const probe = $("#norm-probe-info");
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

  if (window.DJMM && typeof window.DJMM.setPlayerTrack === "function") {
    window.DJMM.setPlayerTrack(selectedFile, selectedFile.split("/").pop() || "Track");
  }

  runAnalysis(selectedFile);
}

function normPageFocusedFieldConsumesArrowKeys(el) {
  if (!el || el.nodeType !== Node.ELEMENT_NODE) return false;
  if (el.isContentEditable) return true;
  const tag = el.tagName.toLowerCase();
  if (tag === "textarea" || tag === "select") return true;
  if (tag === "input") {
    const type = (el.type || "text").toLowerCase();
    const textual = new Set(["", "text", "search", "url", "email", "password", "tel", "number", "date", "time", "datetime-local", "month", "week"]);
    return textual.has(type);
  }
  return false;
}

function wireNormFileListArrowNav() {
  if (window.__normFileListKbWired) return;
  window.__normFileListKbWired = true;
  document.addEventListener(
    "keydown",
    (e) => {
      if (!document.body.classList.contains("page-normalise")) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key !== "ArrowDown" && e.key !== "ArrowUp" && e.key !== "Home" && e.key !== "End") return;
      if (normPageFocusedFieldConsumesArrowKeys(e.target)) return;
      if (DJMM.isFolderPickerOpen()) return;

      const list = document.getElementById("norm-file-list");
      if (!list) return;
      const items = [...list.querySelectorAll(".file-item:not(.file-list-hidden)")];
      if (!items.length) return;

      e.preventDefault();

      let cur = items.findIndex((row) => row.classList.contains("selected"));
      let next = cur;
      if (e.key === "ArrowDown") next = cur < 0 ? 0 : Math.min(cur + 1, items.length - 1);
      else if (e.key === "ArrowUp") next = cur < 0 ? items.length - 1 : Math.max(cur - 1, 0);
      else if (e.key === "Home") next = 0;
      else if (e.key === "End") next = items.length - 1;

      const row = items[next];
      if (row) {
        selectFile(row);
        row.scrollIntoView({ block: "nearest", behavior: "auto" });
      }
    },
    true
  );
}

function formatDuration(secs) {
  const m = Math.floor(secs / 60);
  const s = Math.floor(secs % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

async function runAnalysis(filepath) {
  const panel = $("#norm-analysis-panel");
  panel.classList.remove("hidden");
  panel.querySelector(".level-meters").classList.add("hidden");
  $("#norm-level-verdict").innerHTML = "";

  const existingSpinner = panel.querySelector(".analysis-spinner");
  if (existingSpinner) existingSpinner.remove();

  const spinner = document.createElement("div");
  spinner.className = "analysis-spinner";
  spinner.innerHTML = '<span class="spinner"></span> Analysing audio levels...';
  panel.querySelector(".analysis-header").after(spinner);

  const resp = await fetch("/api/analyse", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ filepath }),
  });
  const data = await resp.json();

  spinner.remove();
  panel.querySelector(".level-meters").classList.remove("hidden");

  if (data.error) {
    $("#norm-level-verdict").innerHTML = `<span class="verdict-low">${data.error}</span>`;
    return;
  }

  currentLoudnormParams = data.loudnorm_params;

  const lufs = data.integrated_lufs;
  const peak = data.true_peak;
  const mean = data.mean_volume;

  setMeter("norm-meter-lufs", "norm-val-lufs", lufs, -60, 0, `${lufs.toFixed(1)} LUFS`);
  setMeter("norm-meter-peak", "norm-val-peak", peak, -60, 0, `${peak.toFixed(1)} dBTP`);
  setMeter(
    "norm-meter-mean",
    "norm-val-mean",
    mean != null ? mean : -60,
    -60,
    0,
    mean != null ? `${mean.toFixed(1)} dB` : "—"
  );

  const target = data.target_lufs;
  const clipping = peak > 0 || lufs > -6;
  const veryHot = lufs > -10 && !clipping;

  let verdict;
  if (clipping) {
    verdict = `<span class="verdict-danger">Likely clipping / extremely hot</span> — true peak ${peak.toFixed(1)} dBTP, ${lufs.toFixed(1)} LUFS. <strong>Normalisation strongly recommended</strong> (will reduce level toward ${target} LUFS).`;
  } else if (veryHot) {
    verdict = `<span class="verdict-ok">Very loud</span> — ${lufs.toFixed(1)} LUFS. Normalisation will tame levels toward ${target} LUFS and reduce inter-sample peaks.`;
  } else if (lufs <= -30) {
    verdict = `<span class="verdict-low">Very quiet</span> — ${Math.abs(lufs - target).toFixed(1)} dB below target. Normalisation will raise level.`;
  } else if (lufs <= -20) {
    verdict = `<span class="verdict-ok">Quiet</span> — normalisation will bring perceived level closer to ${target} LUFS.`;
  } else if (lufs <= -10) {
    verdict = `<span class="verdict-good">Reasonable level</span> — you can still normalise for DJ library consistency.`;
  } else {
    verdict = `<span class="verdict-good">Loud</span> — normalisation may reduce level slightly toward ${target} LUFS.`;
  }

  $("#norm-level-verdict").innerHTML = verdict;
  $("#norm-run-btn").disabled = false;
  scheduleNormalisePageSave();
}

function setMeter(meterId, valueId, value, min, max, label) {
  const pct = Math.max(0, Math.min(100, ((value - min) / (max - min)) * 100));
  const fill = $(`#${meterId}`);
  fill.style.width = `${pct}%`;

  fill.classList.remove("level-low", "level-mid", "level-good", "level-hot");
  if (value <= -30) fill.classList.add("level-low");
  else if (value <= -18) fill.classList.add("level-mid");
  else if (value <= -1) fill.classList.add("level-good");
  else fill.classList.add("level-hot");

  $(`#${valueId}`).textContent = label;
}

async function runNormalise() {
  if (!selectedFile || !currentLoudnormParams) return;

  const btn = $("#norm-run-btn");
  const result = $("#norm-result");
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Normalising...';
  result.classList.add("hidden");

  let suffix = $("#norm-suffix").value.trim() || "_LUFS14";
  if (!suffix.startsWith("_")) suffix = "_" + suffix;

  const resp = await fetch("/api/normalise", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      filepath: selectedFile,
      loudnorm_params: currentLoudnormParams,
      output_suffix: suffix,
    }),
  });

  const data = await resp.json();
  result.classList.remove("hidden");

  if (data.error) {
    result.className = "result error";
    result.innerHTML = `<div class="result-title">Error</div><div class="result-detail">${data.error}</div>`;
  } else {
    result.className = "result";
    result.innerHTML = `
      <div class="result-title">Done</div>
      <div class="result-detail">
        <strong>${data.size_mb} MB</strong><br>
        Wrote: ${data.output_path}<br>
        <span class="hint">Metadata and artwork were copied from the source file. Format: ${data.extract_profile_label || "from Settings"}.</span>
      </div>
    `;
    browseAudio();
  }

  btn.disabled = false;
  const cfgResp = await fetch("/api/settings");
  const cfg = await cfgResp.json();
  updateNormTargetLabels(cfg);
  scheduleNormalisePageSave();
}

// ---------------------------------------------------------------------------
// Batch Normalise
// ---------------------------------------------------------------------------

let lastBulkNormScanCount = 0;
let bulkNormScannedFiles = [];

function escHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function updateBulkNormRunEnabled() {
  const btn = document.getElementById("norm-bulk-run-btn");
  if (btn) btn.disabled = lastBulkNormScanCount < 1;
}

function setBulkNormProgress(visible, label) {
  const wrap = document.getElementById("norm-bulk-progress-wrap");
  const lab = document.getElementById("norm-bulk-progress-label");
  if (!wrap) return;
  wrap.classList.toggle("hidden", !visible);
  wrap.setAttribute("aria-busy", visible ? "true" : "false");
  if (lab && label) lab.textContent = label;
}

async function runBulkNormScan() {
  const root = ($("#norm-bulk-dir")?.value || "").trim();
  const st = document.getElementById("norm-bulk-scan-status");
  st.classList.remove("hidden");
  if (!root) {
    st.textContent = "Set a folder first.";
    lastBulkNormScanCount = 0;
    bulkNormScannedFiles = [];
    updateBulkNormRunEnabled();
    return;
  }
  st.textContent = "Scanning…";
  const rec = document.getElementById("norm-bulk-recursive")?.checked || false;
  const u = new URL("/api/scan-normalise-bulk", window.location.origin);
  u.searchParams.set("dir", root);
  u.searchParams.set("recursive", rec ? "1" : "0");
  const resp = await fetch(u);
  const data = await resp.json();
  if (data.error) {
    st.textContent = data.error;
    lastBulkNormScanCount = 0;
    bulkNormScannedFiles = [];
    updateBulkNormRunEnabled();
    return;
  }
  lastBulkNormScanCount = data.count;
  st.textContent = `Found ${data.count} audio file(s) under ${data.root}`;
  $("#norm-bulk-dir").value = data.root;
  bulkNormScannedFiles = [];
  updateBulkNormRunEnabled();
  scheduleNormalisePageSave();
}

async function runBulkNorm() {
  const root = ($("#norm-bulk-dir")?.value || "").trim();
  if (!root) return;
  const rec = document.getElementById("norm-bulk-recursive")?.checked || false;

  const out = document.getElementById("norm-bulk-result");
  const btn = document.getElementById("norm-bulk-run-btn");
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Normalising…';
  out.classList.add("hidden");

  let suffix = ($("#norm-bulk-suffix")?.value || "_norm").trim() || "_norm";
  if (!suffix.startsWith("_")) suffix = "_" + suffix;

  setBulkNormProgress(true, "Normalising audio files (this may take a while)…");

  let data;
  try {
    const resp = await fetch("/api/normalise-bulk", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        root_dir: root,
        recursive: rec,
        suffix: suffix,
        stream: true,
      }),
    });
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    let lastLine = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const lines = buf.split("\n");
      buf = lines.pop();
      for (const ln of lines) {
        if (!ln.trim()) continue;
        lastLine = ln;
        try {
          const msg = JSON.parse(ln);
          if (msg.type === "progress") {
            setBulkNormProgress(true, `Normalising ${msg.current} / ${msg.total}: ${msg.file}`);
          }
        } catch (_) {}
      }
    }
    if (buf.trim()) lastLine = buf.trim();
    data = JSON.parse(lastLine);
  } catch (e) {
    setBulkNormProgress(false);
    out.classList.remove("hidden");
    out.className = "result error";
    out.innerHTML = `<div class="result-title">Error</div><div class="result-detail">${escHtml(String(e.message || e))}</div>`;
    btn.disabled = false;
    btn.textContent = "Run";
    updateBulkNormRunEnabled();
    return;
  }

  setBulkNormProgress(false);
  out.classList.remove("hidden");

  if (data.error) {
    out.className = "result error";
    out.innerHTML = `<div class="result-title">Error</div><div class="result-detail">${escHtml(data.error)}</div>`;
  } else {
    out.className = "result";
    const s = data.summary || {};
    const parts = [
      `Normalised: <strong>${s.normalised ?? 0}</strong>`,
      `Skipped (already exists): <strong>${s.skipped ?? 0}</strong>`,
      `Errors: <strong>${s.errors ?? 0}</strong>`,
    ];
    let errBlock = "";
    if (data.errors && data.errors.length) {
      const lines = data.errors
        .slice(0, 30)
        .map((e) => `&bull; <span class="mono">${escHtml((e.source || "").split("/").pop())}</span>: ${escHtml(e.error || "")}`)
        .join("<br>");
      errBlock = `<p class="hint" style="margin-top:0.5rem"><strong>Issues:</strong><br/>${lines}</p>`;
      if (data.errors.length > 30) {
        errBlock += `<p class="hint">… and ${data.errors.length - 30} more.</p>`;
      }
    }
    const profileNote = data.extract_profile_label
      ? `<p class="hint" style="margin-top:0.35rem">Output format: ${escHtml(data.extract_profile_label)}</p>`
      : "";
    out.innerHTML = `<div class="result-title">Batch normalise complete</div><div class="result-detail">${parts.join(" · ")}</div>${profileNote}${errBlock}`;
  }

  btn.disabled = false;
  btn.textContent = "Run";
  updateBulkNormRunEnabled();
  scheduleNormalisePageSave();
}

// ---------------------------------------------------------------------------
// Event wiring
// ---------------------------------------------------------------------------

$("#norm-browse-btn").addEventListener("click", browseAudio);
document.getElementById("norm-choose-folder-btn")?.addEventListener("click", async () => {
  let start = $("#norm-dir").value.trim();
  if (!start) {
    const resp = await fetch("/api/settings");
    const cfg = await resp.json();
    start = (cfg.destination_dir || "").trim() || "~";
  }
  DJMM.openFolderPicker({
    startPath: start,
    onSelect(path) {
      $("#norm-dir").value = path;
      browseAudio();
    },
  });
});
$("#norm-dir").addEventListener("keydown", (e) => {
  if (e.key === "Enter") browseAudio();
});
$("#norm-dir").addEventListener("input", scheduleNormalisePageSave);
$("#norm-suffix").addEventListener("input", scheduleNormalisePageSave);
$("#norm-run-btn").addEventListener("click", runNormalise);

// Batch normalise wiring
document.getElementById("norm-bulk-choose-btn")?.addEventListener("click", async () => {
  let start = ($("#norm-bulk-dir")?.value || "").trim();
  if (!start) {
    const resp = await fetch("/api/settings");
    const cfg = await resp.json();
    start = (cfg.destination_dir || "").trim() || "~";
  }
  DJMM.openFolderPicker({
    startPath: start,
    onSelect(path) {
      $("#norm-bulk-dir").value = path;
      lastBulkNormScanCount = 0;
      bulkNormScannedFiles = [];
      const st = document.getElementById("norm-bulk-scan-status");
      if (st) { st.classList.add("hidden"); st.textContent = ""; }
      updateBulkNormRunEnabled();
      scheduleNormalisePageSave();
    },
  });
});
document.getElementById("norm-bulk-scan-btn")?.addEventListener("click", runBulkNormScan);
document.getElementById("norm-bulk-run-btn")?.addEventListener("click", runBulkNorm);
document.getElementById("norm-bulk-dir")?.addEventListener("keydown", (e) => {
  if (e.key === "Enter") runBulkNormScan();
});
document.getElementById("norm-bulk-dir")?.addEventListener("input", scheduleNormalisePageSave);
document.getElementById("norm-bulk-suffix")?.addEventListener("input", scheduleNormalisePageSave);
document.getElementById("norm-bulk-recursive")?.addEventListener("change", scheduleNormalisePageSave);

loadSettings().then(async () => {
  const st = typeof djmmPageStateGetPage === "function" ? djmmPageStateGetPage("normalise") : null;
  if (st && st.v === 1) {
    if (st.normDir != null) $("#norm-dir").value = st.normDir;
    if (st.normSuffix != null) $("#norm-suffix").value = st.normSuffix;
    if (st.normBulkDir != null && $("#norm-bulk-dir")) $("#norm-bulk-dir").value = st.normBulkDir;
    if (st.normBulkSuffix != null && $("#norm-bulk-suffix")) $("#norm-bulk-suffix").value = st.normBulkSuffix;
    if (st.normBulkRecursive != null) {
      const rec = document.getElementById("norm-bulk-recursive");
      if (rec) rec.checked = st.normBulkRecursive;
    }
  }
  await browseAudio();
  if (st && st.v === 1 && st.selectedFile) {
    const items = document.querySelectorAll("#norm-file-list .file-item");
    for (const el of items) {
      if (el.dataset.path === st.selectedFile) {
        await selectFile(el);
        break;
      }
    }
  }
  scheduleNormalisePageSave();
});
