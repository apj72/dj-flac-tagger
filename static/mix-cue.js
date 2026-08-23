const $ = (sel) => document.querySelector(sel);

const MC_DIR_KEY = "djmm.mixcue.dir";
const MC_STATE_KEY = "djmm.mixcue.state";

let currentAudioPath = "";
let currentCuePath = "";
let audioLength = 0;

/* ---------- time helpers ---------- */
function fmtTime(secs) {
  secs = Math.max(0, Math.round(Number(secs) || 0));
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  const s = secs % 60;
  const pad = (n) => String(n).padStart(2, "0");
  return h ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`;
}

function parseTime(str) {
  if (str == null) return NaN;
  str = String(str).trim();
  if (!str) return NaN;
  const parts = str.split(":").map((p) => p.trim());
  if (parts.some((p) => p === "" || isNaN(Number(p)))) return NaN;
  const nums = parts.map(Number);
  if (nums.length === 1) return nums[0];
  if (nums.length === 2) return nums[0] * 60 + nums[1];
  if (nums.length === 3) return nums[0] * 3600 + nums[1] * 60 + nums[2];
  return NaN;
}

/* ---------- draft persistence (survives navigation) ---------- */
function saveState() {
  try {
    const st = {
      v: 1,
      audio_path: currentAudioPath,
      cue_path: currentCuePath,
      audio_length: audioLength,
      mix: {
        title: $("#mc-title").value,
        performer: $("#mc-artist").value,
        album: $("#mc-album").value,
        date: $("#mc-date").value,
      },
      opts: {
        chapters: $("#mc-opt-chapters").checked,
        comment: $("#mc-opt-comment").checked,
        tags: $("#mc-opt-tags").checked,
      },
      tracks: readTrackRows(true),
    };
    localStorage.setItem(MC_STATE_KEY, JSON.stringify(st));
  } catch (e) {
    /* ignore quota / serialization errors */
  }
}

function loadState() {
  try {
    const raw = localStorage.getItem(MC_STATE_KEY);
    if (!raw) return null;
    const st = JSON.parse(raw);
    return st && st.v === 1 && st.audio_path ? st : null;
  } catch (e) {
    return null;
  }
}

function clearState() {
  try {
    localStorage.removeItem(MC_STATE_KEY);
  } catch (e) {
    /* ignore */
  }
}

/* ---------- track rows ---------- */
function makeTrackRow(track) {
  const row = document.createElement("div");
  row.className = "mc-track-row";
  const secs = Number(track.start_seconds) || 0;
  row.dataset.seconds = String(secs);

  const cb = document.createElement("input");
  cb.type = "checkbox";
  cb.checked = track.include !== false;
  cb.title = "Include this track";

  const time = document.createElement("input");
  time.type = "text";
  time.value = track.start_str_display || fmtTime(secs);
  time.className = "mono";
  time.setAttribute("aria-label", "Start time");

  const artist = document.createElement("input");
  artist.type = "text";
  artist.value = track.performer || "";
  artist.placeholder = "Artist";
  artist.setAttribute("aria-label", "Artist");

  const title = document.createElement("input");
  title.type = "text";
  title.value = track.title || "";
  title.placeholder = "Title";
  title.setAttribute("aria-label", "Title");

  const remove = document.createElement("button");
  remove.type = "button";
  remove.className = "btn btn-secondary btn-sm mc-remove";
  remove.textContent = "×";
  remove.title = "Remove track";

  function reflectExcluded() {
    row.classList.toggle("mc-excluded", !cb.checked);
  }
  reflectExcluded();

  cb.addEventListener("change", () => {
    reflectExcluded();
    onEdit();
  });
  time.addEventListener("input", () => {
    const parsed = parseTime(time.value);
    if (!isNaN(parsed)) row.dataset.seconds = String(parsed);
    onEdit();
  });
  artist.addEventListener("input", onEdit);
  title.addEventListener("input", onEdit);
  remove.addEventListener("click", () => {
    row.remove();
    onEdit();
  });

  row.append(cb, time, artist, title, remove);
  return row;
}

function renderTrackRows(tracks) {
  const wrap = $("#mc-tracks");
  wrap.innerHTML = "";
  (tracks || []).forEach((t) => wrap.appendChild(makeTrackRow(t)));
}

function readTrackRows(includeExcluded) {
  const rows = [...document.querySelectorAll("#mc-tracks .mc-track-row")];
  const out = [];
  rows.forEach((row) => {
    const [cb, time, artist, title] = row.querySelectorAll("input");
    const included = cb.checked;
    if (!included && !includeExcluded) return;
    let secs = parseFloat(row.dataset.seconds);
    if (isNaN(secs)) secs = parseTime(time.value);
    if (isNaN(secs)) secs = 0;
    out.push({
      include: included,
      start_seconds: Math.max(0, secs),
      start_str_display: time.value,
      performer: artist.value.trim(),
      title: title.value.trim(),
    });
  });
  return out;
}

/* included tracks, sorted by start time — used for embed + share text */
function collectTracks() {
  return readTrackRows(false)
    .map((t) => ({
      title: t.title,
      performer: t.performer,
      start_seconds: t.start_seconds,
    }))
    .sort((a, b) => a.start_seconds - b.start_seconds);
}

/* ---------- share text ---------- */
function trackLabel(t) {
  const who = (t.performer || "").trim();
  const title = (t.title || "").trim();
  return who ? `${who} - ${title}` : title;
}

function updateShare() {
  const tracks = collectTracks();
  const desc = tracks.map((t) => `${fmtTime(t.start_seconds)}  ${trackLabel(t)}`.trimEnd()).join("\n");
  const list = tracks.map((t, i) => `${i + 1}. ${trackLabel(t)}`.trimEnd()).join("\n");
  $("#mc-share-desc").value = desc;
  $("#mc-share-list").value = list;
}

function onEdit() {
  updateShare();
  saveState();
}

/* ---------- populate editor ---------- */
function populateEditor(data, restoredTracks) {
  const parsed = (data && data.parsed) || {};
  const mix = parsed.mix || {};
  const audio = (data && data.audio) || {};
  currentAudioPath = data.audio_path || currentAudioPath;
  currentCuePath = data.cue_path || currentCuePath;
  audioLength = Number(audio.length_seconds) || Number(data.audio_length) || 0;

  $("#mc-title").value = mix.title || "";
  $("#mc-artist").value = mix.performer || "";
  $("#mc-album").value = "";
  $("#mc-date").value = mix.date || "";

  const tracks = restoredTracks || (parsed.tracks || []).map((t) => ({
    start_seconds: t.start_seconds,
    performer: t.performer,
    title: t.title,
    include: true,
  }));
  renderTrackRows(tracks);

  const info = [];
  if (audioLength) info.push(`length ${fmtTime(audioLength)}`);
  if (parsed.time_mode) info.push(`cue times: ${parsed.time_mode === "hms" ? "h:mm:ss" : "mm:ss:ff"}`);
  if (audio.format) info.push(audio.format);
  $("#mc-audio-info").textContent = info.length ? "· " + info.join(" · ") : "";

  const warn = $("#mc-existing-warning");
  if (audio.has_chapters) {
    warn.textContent = `This file already has ${audio.chapter_count} chapter(s) — embedding will replace them.`;
    warn.classList.remove("hidden");
  } else {
    warn.classList.add("hidden");
  }

  $("#mc-editor").classList.remove("hidden");
  $("#mc-share").classList.remove("hidden");
  updateShare();
}

function applyRestored(st) {
  currentAudioPath = st.audio_path || "";
  currentCuePath = st.cue_path || "";
  audioLength = Number(st.audio_length) || 0;
  $("#mc-title").value = (st.mix && st.mix.title) || "";
  $("#mc-artist").value = (st.mix && st.mix.performer) || "";
  $("#mc-album").value = (st.mix && st.mix.album) || "";
  $("#mc-date").value = (st.mix && st.mix.date) || "";
  if (st.opts) {
    $("#mc-opt-chapters").checked = st.opts.chapters !== false;
    $("#mc-opt-comment").checked = st.opts.comment !== false;
    $("#mc-opt-tags").checked = st.opts.tags !== false;
  }
  renderTrackRows(st.tracks || []);
  const info = [];
  if (audioLength) info.push(`length ${fmtTime(audioLength)}`);
  $("#mc-audio-info").textContent = info.length ? "· " + info.join(" · ") : "";
  $("#mc-editor").classList.remove("hidden");
  $("#mc-share").classList.remove("hidden");
  updateShare();
}

/* ---------- server calls ---------- */
function setLoadStatus(msg, isError) {
  const el = $("#mc-load-status");
  el.textContent = msg || "";
  el.style.color = isError ? "var(--danger)" : "";
  el.classList.toggle("hidden", !msg);
}

async function listMixes(dir) {
  const target = (dir != null ? dir : $("#mc-dir").value).trim();
  setLoadStatus("Listing…");
  const list = $("#mc-file-list");
  list.innerHTML = "";
  try {
    const url = "/api/mix-cue/list" + (target ? "?dir=" + encodeURIComponent(target) : "");
    const resp = await fetch(url);
    const j = await resp.json();
    if (!resp.ok) {
      setLoadStatus(j.error || "Could not list folder", true);
      return;
    }
    $("#mc-dir").value = j.directory || target;
    try {
      localStorage.setItem(MC_DIR_KEY, j.directory || target);
    } catch (e) {}
    if (!j.files.length) {
      setLoadStatus("No audio files in this folder.", false);
      return;
    }
    setLoadStatus("");
    j.files.forEach((f) => {
      const item = document.createElement("div");
      item.className = "file-item";
      item.setAttribute("role", "option");
      const badge = f.has_cue
        ? '<span class="mc-file-badge">cue</span>'
        : '<span class="mc-file-badge mc-no-cue">no cue</span>';
      const size = f.size_mb != null ? ` <span class="hint">${f.size_mb} MB</span>` : "";
      item.innerHTML = `<span>${f.name}</span>${badge}${size}`;
      if (f.has_cue) {
        item.style.cursor = "pointer";
        item.addEventListener("click", () => loadMix(f.path));
      } else {
        item.style.opacity = "0.6";
        item.title = "No paired .cue file";
      }
      list.appendChild(item);
    });
  } catch (e) {
    setLoadStatus("Error: " + e.message, true);
  }
}

async function loadMix(audioPath) {
  setLoadStatus("Reading cue…");
  try {
    const resp = await fetch("/api/mix-cue/parse", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ audio_path: audioPath }),
    });
    const j = await resp.json();
    if (!resp.ok) {
      setLoadStatus(j.error || "Could not read cue", true);
      return;
    }
    setLoadStatus("");
    populateEditor(j, null);
    saveState();
    $("#mc-editor").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (e) {
    setLoadStatus("Error: " + e.message, true);
  }
}

async function reloadFromCue() {
  if (!currentAudioPath) return;
  if (!confirm("Discard your edits and re-read the .cue file?")) return;
  await loadMix(currentAudioPath);
}

function setEmbedStatus(msg, isError) {
  const el = $("#mc-embed-status");
  el.textContent = msg || "";
  el.style.color = isError ? "var(--danger)" : "";
  el.classList.toggle("hidden", !msg);
}

async function embed() {
  if (!currentAudioPath) {
    setEmbedStatus("Load a mix first.", true);
    return;
  }
  const tracks = collectTracks();
  if (!tracks.length) {
    setEmbedStatus("No tracks to write.", true);
    return;
  }
  const btn = $("#mc-embed-btn");
  btn.disabled = true;
  setEmbedStatus("Writing… (large files take a few seconds)");
  try {
    const resp = await fetch("/api/mix-cue/embed", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        audio_path: currentAudioPath,
        mix: {
          title: $("#mc-title").value.trim(),
          performer: $("#mc-artist").value.trim(),
          album: $("#mc-album").value.trim(),
          date: $("#mc-date").value.trim(),
        },
        tracks,
        write_chapters: $("#mc-opt-chapters").checked,
        write_comment: $("#mc-opt-comment").checked,
        write_tags: $("#mc-opt-tags").checked,
      }),
    });
    const j = await resp.json();
    if (!resp.ok) {
      setEmbedStatus(j.error || "Embed failed", true);
      return;
    }
    const bits = [];
    if (j.tags_written) bits.push("tags");
    if (j.comment_written) bits.push("comment");
    if (j.chapters_written) bits.push(`${j.chapters_written} chapters`);
    else if (!j.chapters_supported && $("#mc-opt-chapters").checked)
      bits.push("chapters skipped (format has no chapter support)");
    setEmbedStatus("Saved: " + (bits.join(", ") || "nothing"), false);
    saveState();
  } catch (e) {
    setEmbedStatus("Error: " + e.message, true);
  } finally {
    btn.disabled = false;
  }
}

/* ---------- clipboard ---------- */
async function copyTarget(id) {
  const el = document.getElementById(id);
  if (!el) return;
  const text = el.value;
  try {
    await navigator.clipboard.writeText(text);
  } catch (e) {
    el.removeAttribute("readonly");
    el.select();
    document.execCommand("copy");
    el.setAttribute("readonly", "");
  }
}

/* ---------- default folder ---------- */
async function defaultDir() {
  try {
    const resp = await fetch("/api/settings");
    const cfg = await resp.json();
    return (
      (cfg.capture && (cfg.capture.output_dir || "")).trim() ||
      (cfg.destination_dir || "").trim() ||
      "~"
    );
  } catch (e) {
    return "~";
  }
}

/* ---------- wiring ---------- */
$("#mc-list-btn").addEventListener("click", () => listMixes());
$("#mc-dir").addEventListener("keydown", (e) => {
  if (e.key === "Enter") listMixes();
});
$("#mc-choose-folder-btn").addEventListener("click", async () => {
  const start = $("#mc-dir").value.trim() || (await defaultDir());
  DJMM.openFolderPicker({
    startPath: start || "~",
    onSelect(path) {
      $("#mc-dir").value = path;
      listMixes(path);
    },
  });
});
$("#mc-default-dir-btn").addEventListener("click", async () => {
  const d = await defaultDir();
  $("#mc-dir").value = d;
  listMixes(d);
});
$("#mc-embed-btn").addEventListener("click", embed);
$("#mc-reload-btn").addEventListener("click", reloadFromCue);
$("#mc-add-track-btn").addEventListener("click", () => {
  $("#mc-tracks").appendChild(
    makeTrackRow({ start_seconds: 0, performer: "", title: "", include: true })
  );
  onEdit();
});
["mc-title", "mc-artist", "mc-album", "mc-date"].forEach((id) => {
  document.getElementById(id).addEventListener("input", saveState);
});
["mc-opt-chapters", "mc-opt-comment", "mc-opt-tags"].forEach((id) => {
  document.getElementById(id).addEventListener("change", saveState);
});
document.querySelectorAll(".mc-copy-btn").forEach((btn) => {
  btn.addEventListener("click", async () => {
    await copyTarget(btn.getAttribute("data-target"));
    const prev = btn.textContent;
    btn.textContent = "Copied";
    setTimeout(() => (btn.textContent = prev), 1200);
  });
});

/* ---------- init ---------- */
(async function init() {
  const restored = loadState();
  if (restored) {
    applyRestored(restored);
  }
  let dir = "";
  try {
    dir = localStorage.getItem(MC_DIR_KEY) || "";
  } catch (e) {}
  if (!dir) dir = await defaultDir();
  $("#mc-dir").value = dir;
  listMixes(dir);
})();
