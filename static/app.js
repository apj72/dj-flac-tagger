const $ = (sel) => document.querySelector(sel);

function escHtml(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/** Directory from the last successful Extract browse (server-normalized path). */
let currentBrowseDirectory = "";

/** Fallback extension when API omits filename (matches Settings extract format). */
function extensionForExtractProfile(profileKey) {
  const m = { flac: ".flac", mp3_320: ".mp3", aac_256: ".m4a" };
  return m[profileKey] || ".flac";
}

let selectedFile = null;
let currentTracklist = [];
let currentLoudnormParams = null;

function collectExtractPageState() {
  return {
    v: 1,
    dirInput: $("#dir-input").value,
    retagDir: $("#retag-dir").value,
    selectedFile,
    meta: {
      title: $("#meta-title").value,
      artist: $("#meta-artist").value,
      albumartist: $("#meta-albumartist").value,
      album: $("#meta-album").value,
      date: $("#meta-date").value,
      genre: $("#meta-genre").value,
      comment: $("#meta-comment").value,
      label: $("#meta-label").value,
      catno: $("#meta-catno").value,
    },
    trackUrl: $("#track-url").value,
    trackName: $("#track-name").value,
    artworkUrl: $("#artwork-url").value,
    normalise: $("#normalise").checked,
    deleteSource: $("#delete-source").checked,
    openPlatinumNotes: $("#open-platinum-notes").checked,
    watchPnRepair: $("#watch-pn-repair").checked,
    currentTracklist,
    metaForTracklist: {
      artist: $("#meta-artist").value,
      album: $("#meta-album").value,
      albumartist: $("#meta-albumartist").value,
      date: $("#meta-date").value,
      genre: $("#meta-genre").value,
      label: $("#meta-label").value,
      catno: $("#meta-catno").value,
    },
    historyOpen: !$("#history-body").classList.contains("hidden"),
  };
}

function scheduleExtractPageSave() {
  if (typeof djmmPageStateSchedule === "function") {
    djmmPageStateSchedule("extract", collectExtractPageState);
  }
}

function applyExtractPageStateFields(st) {
  if (st.dirInput != null) $("#dir-input").value = st.dirInput;
  if (st.retagDir != null) $("#retag-dir").value = st.retagDir;
  if (st.meta) {
    const m = st.meta;
    if (m.title != null) $("#meta-title").value = m.title;
    if (m.artist != null) $("#meta-artist").value = m.artist;
    if (m.albumartist != null) $("#meta-albumartist").value = m.albumartist;
    if (m.album != null) $("#meta-album").value = m.album;
    if (m.date != null) $("#meta-date").value = m.date;
    if (m.genre != null) $("#meta-genre").value = m.genre;
    if (m.comment != null) $("#meta-comment").value = m.comment;
    if (m.label != null) $("#meta-label").value = m.label;
    if (m.catno != null) $("#meta-catno").value = m.catno;
  }
  if (st.trackUrl != null) $("#track-url").value = st.trackUrl;
  if (st.trackName != null) $("#track-name").value = st.trackName;
  if (st.artworkUrl != null) $("#artwork-url").value = st.artworkUrl;
  if (st.normalise != null) $("#normalise").checked = st.normalise;
  if (st.deleteSource != null) $("#delete-source").checked = st.deleteSource;
  if (st.openPlatinumNotes != null) $("#open-platinum-notes").checked = st.openPlatinumNotes;
  if (st.watchPnRepair != null) $("#watch-pn-repair").checked = st.watchPnRepair;
}

function wireExtractPagePersistence() {
  const ids = [
    "dir-input",
    "retag-dir",
    "track-url",
    "track-name",
    "meta-title",
    "meta-artist",
    "meta-albumartist",
    "meta-album",
    "meta-date",
    "meta-genre",
    "meta-comment",
    "meta-label",
    "meta-catno",
    "artwork-url",
  ];
  ids.forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.addEventListener("input", scheduleExtractPageSave);
  });
  ["normalise", "delete-source", "open-platinum-notes", "watch-pn-repair"].forEach((id) => {
    document.getElementById(id)?.addEventListener("change", scheduleExtractPageSave);
  });
}

// ---- Load paths from Settings (configured on /settings tab) ----
async function loadExtractPrefs() {
  const resp = await fetch("/api/settings");
  const cfg = await resp.json();
  $("#dir-input").value = cfg.source_dir_resolved || "";
  const dest = (cfg.destination_dir || "").trim();
  if (dest) $("#retag-dir").value = dest;
}

// ---- Browse files ----
async function browseFiles() {
  const dir = $("#dir-input").value.trim() || "";
  const params = dir ? `?dir=${encodeURIComponent(dir)}` : "";
  const resp = await fetch(`/api/browse${params}`);
  const data = await resp.json();

  if (data.error) {
    $("#file-list").innerHTML = `<div class="status">${data.error}</div>`;
    scheduleExtractPageSave();
    return;
  }

  $("#dir-input").value = data.directory;
  currentBrowseDirectory = data.directory;

  if (data.files.length === 0) {
    $("#file-list").innerHTML = `<div class="status">No video files found</div>`;
    scheduleExtractPageSave();
    return;
  }

  $("#file-list").innerHTML = data.files
    .map(
      (f) =>
        `<div class="file-item" data-path="${escHtml(f.path)}">
          <span class="file-item-main file-name">${escHtml(f.name)}</span>
          <span class="file-item-meta">
            <span class="file-size">${f.size_mb} MB</span>
            <span class="file-item-actions">
              <button type="button" class="btn btn-secondary file-rename-btn" data-path="${escHtml(f.path)}" title="Rename recording (same folder)">Rename</button>
              <button type="button" class="btn btn-secondary file-delete-btn" data-path="${escHtml(f.path)}" title="Move to Bin (macOS)">Delete</button>
            </span>
          </span>
        </div>`,
    )
    .join("");

  document.querySelectorAll(".file-item").forEach((el) => {
    el.addEventListener("click", () => selectFile(el));
  });
  document.querySelectorAll(".file-rename-btn").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      void onRenameSourceRecording(btn.dataset.path);
    });
  });
  document.querySelectorAll(".file-delete-btn").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      void onDeleteSourceRecording(btn.dataset.path);
    });
  });
  scheduleExtractPageSave();
}

// ---- In-app dialogs (match main UI; avoid native prompt/alert/confirm) ----
function extractShowAlert(title, message) {
  return new Promise((resolve) => {
    const modal = document.getElementById("extract-alert-modal");
    const ok = document.getElementById("extract-alert-ok");
    document.getElementById("extract-alert-title").textContent = title;
    document.getElementById("extract-alert-body").textContent = message;
    let done = false;
    function finish() {
      if (done) return;
      done = true;
      modal.classList.add("hidden");
      ok.removeEventListener("click", onOk);
      document.removeEventListener("keydown", onDocKey);
      modal.removeEventListener("click", onOverlay);
      resolve();
    }
    function onOk() {
      finish();
    }
    function onDocKey(e) {
      if (e.key === "Escape") finish();
    }
    function onOverlay(e) {
      if (e.target === modal) finish();
    }
    ok.addEventListener("click", onOk);
    document.addEventListener("keydown", onDocKey);
    modal.addEventListener("click", onOverlay);
    modal.classList.remove("hidden");
    requestAnimationFrame(() => ok.focus());
  });
}

function extractShowConfirm(title, message, okText, destructive) {
  return new Promise((resolve) => {
    const modal = document.getElementById("extract-confirm-modal");
    const okBtn = document.getElementById("extract-confirm-ok");
    const cancelBtn = document.getElementById("extract-confirm-cancel");
    document.getElementById("extract-confirm-title").textContent = title;
    document.getElementById("extract-confirm-body").textContent = message;
    okBtn.textContent = okText;
    okBtn.className = destructive ? "btn btn-danger" : "btn btn-primary";
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
    function onOk() {
      finish(true);
    }
    function onCancel() {
      finish(false);
    }
    function onDocKey(e) {
      if (e.key === "Escape") onCancel();
    }
    function onOverlay(e) {
      if (e.target === modal) onCancel();
    }
    okBtn.addEventListener("click", onOk);
    cancelBtn.addEventListener("click", onCancel);
    document.addEventListener("keydown", onDocKey);
    modal.addEventListener("click", onOverlay);
    modal.classList.remove("hidden");
    requestAnimationFrame(() => okBtn.focus());
  });
}

function extractShowRenameDialog(displayName, initialStem) {
  return new Promise((resolve) => {
    const modal = document.getElementById("extract-rename-modal");
    const inp = document.getElementById("extract-rename-input");
    const submitBtn = document.getElementById("extract-rename-submit");
    const cancelBtn = document.getElementById("extract-rename-cancel");
    document.getElementById("extract-rename-current").textContent = `Current file: ${displayName}`;
    inp.value = initialStem;
    let done = false;
    function close(result) {
      if (done) return;
      done = true;
      modal.classList.add("hidden");
      inp.onkeydown = null;
      submitBtn.removeEventListener("click", onSubmit);
      cancelBtn.removeEventListener("click", onCancel);
      document.removeEventListener("keydown", onDocKey);
      modal.removeEventListener("click", onOverlay);
      resolve(result);
    }
    function onSubmit() {
      const v = inp.value.trim();
      if (!v) {
        inp.focus();
        return;
      }
      close(v);
    }
    function onCancel() {
      close(null);
    }
    function onDocKey(e) {
      if (e.key === "Escape") onCancel();
    }
    function onOverlay(e) {
      if (e.target === modal) onCancel();
    }
    inp.onkeydown = (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        onSubmit();
      }
    };
    submitBtn.addEventListener("click", onSubmit);
    cancelBtn.addEventListener("click", onCancel);
    document.addEventListener("keydown", onDocKey);
    modal.addEventListener("click", onOverlay);
    modal.classList.remove("hidden");
    requestAnimationFrame(() => {
      inp.focus();
      inp.select();
    });
  });
}

function clearFileSelection() {
  document.querySelectorAll("#file-list .file-item").forEach((e) => e.classList.remove("selected"));
  selectedFile = null;
  currentLoudnormParams = null;
  $("#probe-info").classList.add("hidden");
  $("#analysis-panel").classList.add("hidden");
  updateExtractButton();
  scheduleExtractPageSave();
}

async function onRenameSourceRecording(filepath) {
  const base = currentBrowseDirectory;
  if (!base) {
    await extractShowAlert(
      "Browse first",
      "Use Browse so the folder matches this list, then try again.",
    );
    return;
  }
  const name = filepath.split("/").pop() || "";
  const dot = name.lastIndexOf(".");
  const stem = dot > 0 ? name.slice(0, dot) : name;
  const newStem = await extractShowRenameDialog(name, stem);
  if (!newStem) return;
  const resp = await fetch("/api/source-recording/rename", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ filepath, base_dir: base, new_stem: newStem }),
  });
  const data = await resp.json();
  if (data.error) {
    await extractShowAlert("Could not rename", data.error);
    return;
  }
  const prevSel = selectedFile;
  await browseFiles();
  if (prevSel === filepath && data.path) {
    const items = document.querySelectorAll("#file-list .file-item");
    for (const el of items) {
      if (el.dataset.path === data.path) {
        await selectFile(el);
        break;
      }
    }
  }
  scheduleExtractPageSave();
}

async function onDeleteSourceRecording(filepath) {
  if (!currentBrowseDirectory) {
    await extractShowAlert(
      "Browse first",
      "Use Browse so the folder matches this list, then try again.",
    );
    return;
  }
  const name = filepath.split("/").pop() || "file";
  const ok = await extractShowConfirm(
    "Move to Bin?",
    `“${name}” will be moved to the Bin. You can restore it from Finder on macOS.`,
    "Move to Bin",
    true,
  );
  if (!ok) return;
  const resp = await fetch("/api/source-recording/delete", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ filepath, base_dir: currentBrowseDirectory }),
  });
  const data = await resp.json();
  if (data.error) {
    await extractShowAlert("Could not delete", data.error);
    return;
  }
  if (selectedFile === filepath) clearFileSelection();
  await browseFiles();
  scheduleExtractPageSave();
}

async function selectFile(el) {
  document.querySelectorAll(".file-item").forEach((e) => e.classList.remove("selected"));
  el.classList.add("selected");
  selectedFile = el.dataset.path;
  currentLoudnormParams = null;
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
    scheduleExtractPageSave();
    return;
  }

  const dur = data.duration ? formatDuration(parseFloat(data.duration)) : "?";
  probe.innerHTML = `
    <span><strong>Audio:</strong> ${(data.codec || "?").toUpperCase()}</span>
    <span><strong>Rate:</strong> ${data.sample_rate || "?"} Hz</span>
    <span><strong>Channels:</strong> ${data.channels || "?"}</span>
    <span><strong>Duration:</strong> ${dur}</span>
  `;

  runAnalysis(selectedFile);
  scheduleExtractPageSave();
}

function formatDuration(secs) {
  const m = Math.floor(secs / 60);
  const s = Math.floor(secs % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

// ---- Audio analysis ----
async function runAnalysis(filepath) {
  const panel = $("#analysis-panel");
  panel.classList.remove("hidden");
  panel.querySelector(".level-meters").classList.add("hidden");
  $("#level-verdict").innerHTML = "";

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
    $("#level-verdict").innerHTML = `<span class="verdict-low">${data.error}</span>`;
    return;
  }

  currentLoudnormParams = data.loudnorm_params;

  const lufs = data.integrated_lufs;
  const peak = data.true_peak;
  const mean = data.mean_volume;

  setMeter("meter-lufs", "val-lufs", lufs, -60, 0, `${lufs.toFixed(1)} LUFS`);
  setMeter("meter-peak", "val-peak", peak, -60, 0, `${peak.toFixed(1)} dBTP`);
  setMeter("meter-mean", "val-mean", mean != null ? mean : -60, -60, 0,
    mean != null ? `${mean.toFixed(1)} dB` : "—");

  const target = data.target_lufs;
  const diff = lufs - target;
  let verdict;

  if (lufs <= -30) {
    verdict = `<span class="verdict-low">Very quiet</span> — ${Math.abs(diff).toFixed(1)} dB below target (${target} LUFS). <strong>Normalisation recommended.</strong>`;
    $("#normalise").checked = true;
  } else if (lufs <= -20) {
    verdict = `<span class="verdict-ok">Quiet</span> — ${Math.abs(diff).toFixed(1)} dB below target (${target} LUFS). Normalisation suggested.`;
    $("#normalise").checked = true;
  } else if (lufs <= -10) {
    verdict = `<span class="verdict-good">Good level</span> — ${Math.abs(diff).toFixed(1)} dB from target (${target} LUFS).`;
    $("#normalise").checked = false;
  } else {
    verdict = `<span class="verdict-good">Loud</span> — above target (${target} LUFS). No normalisation needed.`;
    $("#normalise").checked = false;
  }

  $("#level-verdict").innerHTML = verdict;
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
  scheduleExtractPageSave();
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
  scheduleExtractPageSave();
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
  document.querySelectorAll(".track-item").forEach((e) => e.classList.remove("selected"));
  el.classList.add("selected");

  const idx = parseInt(el.dataset.index);
  const track = currentTracklist[idx];

  $("#meta-title").value = track.title;
  $("#meta-artist").value = track.artist || meta.artist || "";
  if (meta.albumartist) $("#meta-albumartist").value = meta.albumartist;
  if (meta.album) $("#meta-album").value = meta.album;
  if (meta.date) $("#meta-date").value = meta.date;
  if (meta.genre) $("#meta-genre").value = meta.genre;
  if (meta.label) $("#meta-label").value = meta.label;
  if (meta.catno) $("#meta-catno").value = meta.catno;

  $("#meta-comment").value = `${track.position} - ${meta.album || ""}`.trim();

  updateExtractButton();
  scheduleExtractPageSave();
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
  scheduleExtractPageSave();
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
  const metadata_source_url = $("#track-url").value.trim();
  const deleteSource = $("#delete-source").checked;
  const normalise = $("#normalise").checked;

  const resp = await fetch("/api/extract", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      filepath: selectedFile,
      metadata,
      artwork_url: artworkUrl,
      metadata_source_url,
      delete_source: deleteSource,
      normalise,
      loudnorm_params: normalise ? currentLoudnormParams : null,
      open_platinum_notes: $("#open-platinum-notes").checked,
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
    const outName = data.filename || `${data.title}${extensionForExtractProfile(data.extract_profile)}`;
    const fmtLabel = data.extract_profile_label || "FLAC (lossless)";
    const lossHint = data.is_lossless_output ? "lossless" : "lossy";
    const lines = [
      `<strong>${outName}</strong> (${data.size_mb} MB)`,
      `Source codec: ${data.source_codec.toUpperCase()} &rarr; ${fmtLabel} (${lossHint})`,
    ];
    if (data.normalised) {
      const lu = data.target_lufs != null ? data.target_lufs : "";
      const tp = data.target_tp != null ? data.target_tp : "";
      lines.push(`Normalised to ${lu} LUFS, ${tp} dBTP peak (EBU R128)`);
      if (data.loudness_retried) {
        lines.push(
          "Loudness was re-checked: output did not pass verification at first, so the app re-encoded once from a fresh source analysis (safe to open in Platinum Notes if no warning below)."
        );
      }
      if (data.loudness_verify_warning) {
        lines.push(
          `<span style="color:var(--danger);display:block;margin-top:0.35rem">Loudness warning: ${data.loudness_verify_warning}</span>`
        );
      }
    }
    lines.push(`Saved to: ${data.output_path}`);
    if (data.copied_to) lines.push(`Copied to: ${data.copied_to}`);
    if (data.copy_error) lines.push(`Copy failed: ${data.copy_error}`);
    if (data.source_trashed) lines.push(`Source recording moved to Bin`);
    if (data.source_trash_error) lines.push(`Could not trash source: ${data.source_trash_error}`);

    result.innerHTML = `
      <div class="result-title">Done!</div>
      <div class="result-detail">${lines.join("<br>")}</div>
    `;
    if ($("#watch-pn-repair").checked && data.output_path && data.log_index != null) {
      result.querySelector(".result-detail").insertAdjacentHTML(
        "beforeend",
        '<div id="pn-watch-msg" class="hint" style="margin-top:0.75rem">Waiting for Platinum Notes output…</div>'
      );
      pollAndRepairPn(data.output_path, data.log_index, data.copied_to || "");
    }
    if (data.source_trashed) {
      browseFiles();
    }
    if (!$("#history-body").classList.contains("hidden")) loadHistory();
  }

  btn.disabled = false;
  btn.textContent = "Extract & Apply Tags";
  scheduleExtractPageSave();
}

function updateExtractButton() {
  $("#extract-btn").disabled = !selectedFile;
}

// ---- Event listeners ----
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
  scheduleExtractPageSave();
});

$("#extract-btn").addEventListener("click", extractAndTag);
$("#clear-btn").addEventListener("click", clearAllFields);

// ---- History / Processing Log ----
let logEntries = [];

function toggleHistory() {
  const body = $("#history-body");
  const arrow = $("#history-arrow");
  body.classList.toggle("hidden");
  arrow.classList.toggle("open");
  if (!body.classList.contains("hidden")) loadHistory();
}

async function loadHistory() {
  const resp = await fetch("/api/log");
  logEntries = await resp.json();
  renderHistory();
}

function renderHistory() {
  const list = $("#history-list");
  if (!logEntries.length) {
    list.innerHTML = '<div class="status">No processed tracks yet.</div>';
    return;
  }

  list.innerHTML = logEntries
    .slice()
    .reverse()
    .map((entry, ri) => {
      const i = logEntries.length - 1 - ri;
      const m = entry.metadata || {};
      const ts = entry.timestamp ? new Date(entry.timestamp).toLocaleDateString() : "";
      const kind = entry.kind === "fix" ? "fix" : "ext";
      const src =
        entry.metadata_source_url && entry.metadata_source_type
          ? `<span class="history-src" title="${entry.metadata_source_url.replace(/"/g, "&quot;")}">${entry.metadata_source_type}</span>`
          : entry.metadata_source_url
            ? `<span class="history-src" title="${entry.metadata_source_url.replace(/"/g, "&quot;")}">link</span>`
            : `<span class="history-src muted">—</span>`;
      return `<div class="history-item" data-index="${i}">
        <label class="history-check"><input type="checkbox" data-idx="${i}" class="log-check" /></label>
        <span class="history-kind">${kind}</span>
        <span class="history-title">${m.title || entry.filename || "Untitled"}</span>
        <span class="history-artist">${m.artist || ""}</span>
        <span class="history-src-col">${src}</span>
        <span class="history-date">${ts}</span>
      </div>`;
    })
    .join("");

  document.querySelectorAll(".log-check").forEach((cb) => {
    cb.addEventListener("change", updateRetagButton);
  });
}

function updateRetagButton() {
  const checked = document.querySelectorAll(".log-check:checked");
  $("#retag-selected-btn").disabled = checked.length === 0;
}

async function retagSelected() {
  const indices = [...document.querySelectorAll(".log-check:checked")].map((cb) =>
    parseInt(cb.dataset.idx)
  );
  if (!indices.length) return;
  await doRetag(indices);
}

async function retagAll() {
  await doRetag(null);
}

async function doRetag(entryIndices) {
  const targetDir = $("#retag-dir").value.trim();
  if (!targetDir) {
    showRetagStatus("Enter a target folder first.", true);
    return;
  }

  const btn = entryIndices ? $("#retag-selected-btn") : $("#retag-all-btn");
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Re-tagging...';

  const body = { target_dir: targetDir };
  if (entryIndices) body.entries = entryIndices;

  const resp = await fetch("/api/retag-batch", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  const data = await resp.json();
  btn.textContent = entryIndices ? "Re-tag Selected" : "Re-tag All in Folder";
  btn.disabled = false;

  if (data.error) {
    showRetagStatus(data.error, true);
    return;
  }

  const ok = data.results.filter((r) => r.status === "ok").length;
  const skipped = data.results.filter((r) => r.status === "skipped").length;
  const errors = data.results.filter((r) => r.status === "error").length;
  showRetagStatus(`Done: ${ok} re-tagged, ${skipped} skipped, ${errors} errors.`, errors > 0);
}

function showRetagStatus(msg, isError) {
  const el = $("#retag-status");
  el.classList.remove("hidden");
  el.className = isError ? "status error" : "status";
  el.textContent = msg;
  setTimeout(() => el.classList.add("hidden"), 5000);
}

$("#history-toggle").addEventListener("click", () => {
  toggleHistory();
  scheduleExtractPageSave();
});
$("#retag-selected-btn").addEventListener("click", retagSelected);
$("#retag-all-btn").addEventListener("click", retagAll);

async function pollAndRepairPn(baseFlacPath, logIndex, copiedTo) {
  const watchEl = $("#pn-watch-msg");
  const end = Date.now() + 180000;
  const cfgResp = await fetch("/api/settings");
  const cfg = await cfgResp.json();
  const suffix = ((cfg.pn_output_suffix || "_PN") + "").trim() || "_PN";

  while (Date.now() < end) {
    await new Promise((r) => setTimeout(r, 2000));
    const resp = await fetch("/api/poll-pn-derivative", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        base_flac_path: baseFlacPath,
        pn_output_suffix: suffix,
        copied_to: copiedTo || "",
      }),
    });
    const d = await resp.json();
    if (d.error && d.ready === undefined) {
      if (watchEl) watchEl.textContent = `Could not watch for PN file: ${d.error}`;
      return;
    }
    if (d.ready) {
      if (watchEl) watchEl.textContent = "Found PN output — applying tags and artwork…";
      const rep = await fetch("/api/repair-pn-derivative", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          base_flac_path: baseFlacPath,
          pn_flac_path: d.pn_path || d.pn_flac_path,
          log_index: logIndex,
          pn_output_suffix: suffix,
        }),
      });
      const fix = await rep.json();
      if (fix.error) {
        if (watchEl) watchEl.textContent = `Repair failed: ${fix.error}`;
        return;
      }
      const parts = [`Re-tagged: ${fix.pn_path || fix.pn_flac_path}`];
      if (fix.copied_pn_to_destination) parts.push(`Copied to: ${fix.copied_pn_to_destination}`);
      if (fix.copy_error) parts.push(`Copy note: ${fix.copy_error}`);
      if (watchEl) watchEl.innerHTML = parts.join("<br>");
      if (!$("#history-body").classList.contains("hidden")) loadHistory();
      return;
    }
  }
  if (watchEl) {
    watchEl.textContent =
      "Timed out waiting for Platinum Notes. When the _PN file exists, use Processing Log to re-tag that file, or run Repair from the API.";
  }
}

// ---- Init ----
loadExtractPrefs().then(async () => {
  const st = typeof djmmPageStateGetPage === "function" ? djmmPageStateGetPage("extract") : null;
  if (st && st.v === 1) applyExtractPageStateFields(st);
  await browseFiles();
  if (st && st.v === 1 && st.selectedFile) {
    const items = document.querySelectorAll("#file-list .file-item");
    for (const el of items) {
      if (el.dataset.path === st.selectedFile) {
        await selectFile(el);
        break;
      }
    }
  }
  if (st && st.v === 1 && st.currentTracklist && st.currentTracklist.length > 1) {
    currentTracklist = st.currentTracklist;
    showTracklist(st.currentTracklist, st.metaForTracklist || {});
  }
  if (st && st.v === 1 && st.historyOpen) {
    $("#history-body").classList.remove("hidden");
    $("#history-arrow").classList.add("open");
    loadHistory();
  }
  wireExtractPagePersistence();
  scheduleExtractPageSave();
});
