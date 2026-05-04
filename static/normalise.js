const $ = (sel) => document.querySelector(sel);

let selectedFile = null;
let currentLoudnormParams = null;

function collectNormalisePageState() {
  return {
    v: 1,
    normDir: $("#norm-dir").value,
    normSuffix: $("#norm-suffix").value,
    selectedFile,
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

$("#norm-browse-btn").addEventListener("click", browseAudio);
$("#norm-dir").addEventListener("keydown", (e) => {
  if (e.key === "Enter") browseAudio();
});
$("#norm-dir").addEventListener("input", scheduleNormalisePageSave);
$("#norm-suffix").addEventListener("input", scheduleNormalisePageSave);
$("#norm-run-btn").addEventListener("click", runNormalise);

loadSettings().then(async () => {
  const st = typeof djmmPageStateGetPage === "function" ? djmmPageStateGetPage("normalise") : null;
  if (st && st.v === 1) {
    if (st.normDir != null) $("#norm-dir").value = st.normDir;
    if (st.normSuffix != null) $("#norm-suffix").value = st.normSuffix;
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
