const $ = (sel) => document.querySelector(sel);


function linesToRetainSuffixArray(text) {
  return (text || "")
    .split("\n")
    .map((ln) => ln.trim())
    .filter((ln) => ln && !ln.startsWith("#"));
}

function collectSettingsPageDraft() {
  return {
    v: 1,
    page_background_enabled:
      typeof djmmGetPageBackgroundEnabled === "function" ? djmmGetPageBackgroundEnabled() : true,
    source_dir: $("#cfg-source").value,
    destination_dir: $("#cfg-dest").value,
    fix_metadata_default_dir: $("#cfg-fix-default").value,
    inspect_default_dir: $("#cfg-inspect-default").value,
    capture_output_dir: $("#cfg-capture-output").value,
    extract_profile: $("#cfg-extract-profile").value,
    mp3_bitrate: $("#cfg-mp3-bitrate").value,
    aac_bitrate: $("#cfg-aac-bitrate").value,
    platinum_notes_app: $("#cfg-pn-app").value,
    pn_output_suffix: $("#cfg-pn-suffix").value,
    target_lufs: $("#cfg-target-lufs").value,
    target_true_peak: $("#cfg-target-tp").value,
    loudness_verify_enabled: $("#cfg-loudness-verify").checked,
    extract_mkv_audio_analysis_enabled: $("#cfg-mkv-extract-analysis").checked,
    fix_retain_filename_suffixes_text: $("#cfg-fix-retain-suffixes").value,
  };
}

function scheduleSettingsPageSave() {
  if (typeof djmmPageStateSchedule === "function") {
    djmmPageStateSchedule("settings", collectSettingsPageDraft);
  }
}

function applySettingsDraft(st) {
  if (st.page_background_enabled != null && typeof djmmApplyPageBackgroundEnabled === "function") {
    djmmApplyPageBackgroundEnabled(!!st.page_background_enabled);
    const pg = document.getElementById("cfg-page-background");
    if (pg) pg.checked = !!st.page_background_enabled;
  }
  if (st.source_dir != null) $("#cfg-source").value = st.source_dir;
  if (st.destination_dir != null) $("#cfg-dest").value = st.destination_dir;
  if (st.fix_metadata_default_dir != null) $("#cfg-fix-default").value = st.fix_metadata_default_dir;
  if (st.inspect_default_dir != null) $("#cfg-inspect-default").value = st.inspect_default_dir;
  if (st.capture_output_dir != null) $("#cfg-capture-output").value = st.capture_output_dir;
  if (st.extract_profile != null) {
    const sel = $("#cfg-extract-profile");
    if ([...sel.options].some((o) => o.value === st.extract_profile)) sel.value = st.extract_profile;
  }
  if (st.mp3_bitrate != null) {
    const sel = $("#cfg-mp3-bitrate");
    if (sel && [...sel.options].some((o) => o.value === st.mp3_bitrate)) sel.value = st.mp3_bitrate;
  }
  if (st.aac_bitrate != null) {
    const sel = $("#cfg-aac-bitrate");
    if (sel && [...sel.options].some((o) => o.value === st.aac_bitrate)) sel.value = st.aac_bitrate;
  }
  updateBitrateVisibility();
  if (st.platinum_notes_app != null) $("#cfg-pn-app").value = st.platinum_notes_app;
  if (st.pn_output_suffix != null) $("#cfg-pn-suffix").value = st.pn_output_suffix;
  if (st.target_lufs != null) $("#cfg-target-lufs").value = st.target_lufs;
  if (st.target_true_peak != null) $("#cfg-target-tp").value = st.target_true_peak;
  if (st.loudness_verify_enabled != null) $("#cfg-loudness-verify").checked = st.loudness_verify_enabled;
  if (st.extract_mkv_audio_analysis_enabled != null) {
    $("#cfg-mkv-extract-analysis").checked = st.extract_mkv_audio_analysis_enabled;
  }
  if (st.fix_retain_filename_suffixes_text != null) {
    $("#cfg-fix-retain-suffixes").value = st.fix_retain_filename_suffixes_text;
  }
}

function updateBitrateVisibility() {
  const profile = $("#cfg-extract-profile").value;
  $("#mp3-bitrate-row").style.display = profile === "mp3" ? "" : "none";
  $("#aac-bitrate-row").style.display = profile === "aac" ? "" : "none";
}

function fillBitrateSelects(cfg) {
  const mp3Sel = $("#cfg-mp3-bitrate");
  const aacSel = $("#cfg-aac-bitrate");
  const mp3Opts = cfg.mp3_bitrate_options || ["128", "192", "256", "320"];
  const aacOpts = cfg.aac_bitrate_options || ["128", "192", "256", "320"];
  mp3Sel.innerHTML = mp3Opts.map((b) => `<option value="${b}">${b}</option>`).join("");
  aacSel.innerHTML = aacOpts.map((b) => `<option value="${b}">${b}</option>`).join("");
  mp3Sel.value = cfg.mp3_bitrate || "320";
  aacSel.value = cfg.aac_bitrate || "256";
}

function fillExtractProfileSelect(cfg) {
  const sel = $("#cfg-extract-profile");
  const profiles = cfg.extract_profiles || [];
  const current = cfg.extract_profile || "flac";
  sel.innerHTML = profiles
    .map((p) => `<option value="${p.key}">${p.label}</option>`)
    .join("");
  if (profiles.some((p) => p.key === current)) sel.value = current;
  else sel.value = profiles[0]?.key || "flac";
}

async function loadSettings() {
  const resp = await fetch("/api/settings");
  const cfg = await resp.json();
  fillExtractProfileSelect(cfg);
  fillBitrateSelects(cfg);
  updateBitrateVisibility();
  $("#cfg-source").value = cfg.source_dir || "";
  $("#cfg-dest").value = cfg.destination_dir || "";
  $("#cfg-fix-default").value = cfg.fix_metadata_default_dir || "";
  $("#cfg-inspect-default").value = cfg.inspect_default_dir || "";
  $("#cfg-capture-output").value = (cfg.capture && cfg.capture.output_dir) || "";
  $("#cfg-pn-app").value = cfg.platinum_notes_app || "";
  $("#cfg-pn-suffix").value = cfg.pn_output_suffix || "_PN";
  $("#cfg-target-lufs").value =
    cfg.target_lufs !== undefined && cfg.target_lufs !== null ? String(cfg.target_lufs) : "-14";
  $("#cfg-target-tp").value =
    cfg.target_true_peak !== undefined && cfg.target_true_peak !== null
      ? String(cfg.target_true_peak)
      : "-1";
  $("#cfg-loudness-verify").checked = cfg.loudness_verify_enabled !== false;
  $("#cfg-mkv-extract-analysis").checked = cfg.extract_mkv_audio_analysis_enabled !== false;
  const sfx = cfg.fix_retain_filename_suffixes;
  $("#cfg-fix-retain-suffixes").value = Array.isArray(sfx) && sfx.length ? sfx.join("\n") : "";
  const draft = typeof djmmPageStateGetPage === "function" ? djmmPageStateGetPage("settings") : null;
  if (draft && draft.v === 1) applySettingsDraft(draft);
}

async function saveSettings() {
  const resp = await fetch("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      source_dir: $("#cfg-source").value.trim(),
      destination_dir: $("#cfg-dest").value.trim(),
      fix_metadata_default_dir: $("#cfg-fix-default").value.trim(),
      inspect_default_dir: $("#cfg-inspect-default").value.trim(),
      capture_output_dir: $("#cfg-capture-output").value.trim(),
      extract_profile: $("#cfg-extract-profile").value,
      mp3_bitrate: $("#cfg-mp3-bitrate").value,
      aac_bitrate: $("#cfg-aac-bitrate").value,
      platinum_notes_app: $("#cfg-pn-app").value.trim(),
      pn_output_suffix: $("#cfg-pn-suffix").value.trim() || "_PN",
      target_lufs: $("#cfg-target-lufs").value.trim(),
      target_true_peak: $("#cfg-target-tp").value.trim(),
      loudness_verify_enabled: $("#cfg-loudness-verify").checked,
      extract_mkv_audio_analysis_enabled: $("#cfg-mkv-extract-analysis").checked,
      fix_retain_filename_suffixes: linesToRetainSuffixArray($("#cfg-fix-retain-suffixes").value),
    }),
  });
  let j = {};
  try {
    j = await resp.json();
  } catch (e) {
    j = {};
  }
  if (!resp.ok || (j && j.error)) {
    const status = $("#settings-status");
    status.classList.remove("hidden");
    status.style.color = "var(--danger)";
    status.textContent = j.error;
    setTimeout(() => {
      status.classList.add("hidden");
      status.style.color = "";
    }, 6000);
    return;
  }

  if (typeof djmmPageStateSetPage === "function") {
    djmmPageStateSetPage("settings", null);
  }

  const status = $("#settings-status");
  status.style.color = "";
  status.classList.remove("hidden");
  status.textContent = "Saved";
  setTimeout(() => status.classList.add("hidden"), 2000);
}

function wireThemeControl() {
  const sel = document.getElementById("cfg-theme");
  if (!sel || typeof djmmGetThemePreference !== "function") return;
  sel.value = djmmGetThemePreference();
  sel.addEventListener("change", () => {
    if (typeof djmmApplyThemePreference === "function") {
      djmmApplyThemePreference(sel.value);
    }
  });
}

function wirePageBackgroundControl() {
  const cb = document.getElementById("cfg-page-background");
  if (!cb || typeof djmmGetPageBackgroundEnabled !== "function") return;
  cb.checked = djmmGetPageBackgroundEnabled();
  cb.addEventListener("change", () => {
    if (typeof djmmApplyPageBackgroundEnabled === "function") {
      djmmApplyPageBackgroundEnabled(cb.checked);
    }
    scheduleSettingsPageSave();
  });
}

function wireSettingsPersistence() {
  [
    "cfg-source",
    "cfg-dest",
    "cfg-fix-default",
    "cfg-inspect-default",
    "cfg-capture-output",
    "cfg-extract-profile",
    "cfg-mp3-bitrate",
    "cfg-aac-bitrate",
    "cfg-pn-app",
    "cfg-pn-suffix",
    "cfg-target-lufs",
    "cfg-target-tp",
  ].forEach((id) => {
    document.getElementById(id)?.addEventListener("input", scheduleSettingsPageSave);
    document.getElementById(id)?.addEventListener("change", scheduleSettingsPageSave);
  });
  document.getElementById("cfg-loudness-verify")?.addEventListener("change", scheduleSettingsPageSave);
  document.getElementById("cfg-mkv-extract-analysis")?.addEventListener("change", scheduleSettingsPageSave);
  document.getElementById("cfg-fix-retain-suffixes")?.addEventListener("input", scheduleSettingsPageSave);
}

async function resolveStartPathForSetting(inputId) {
  const input = document.getElementById(inputId);
  const trimmed = input && input.value ? input.value.trim() : "";
  if (trimmed) return trimmed;
  const resp = await fetch("/api/settings");
  const cfg = await resp.json();
  switch (inputId) {
    case "cfg-source":
      return (((cfg.source_dir || "") + "").trim() || "~");
    case "cfg-dest":
      return (((cfg.destination_dir || "") + "").trim() || "~");
    case "cfg-fix-default": {
      const fd = ((cfg.fix_metadata_default_dir || "") + "").trim();
      if (fd) return fd;
      return (((cfg.destination_dir || "") + "").trim() || "~");
    }
    case "cfg-inspect-default": {
      const id = ((cfg.inspect_default_dir || "") + "").trim();
      if (id) return id;
      return (((cfg.destination_dir || "") + "").trim() || "~");
    }
    case "cfg-capture-output": {
      const co = (cfg.capture && cfg.capture.output_dir || "").trim();
      if (co) return co;
      return (((cfg.destination_dir || "") + "").trim() || "~");
    }
    default:
      return "~";
  }
}

function wireSettingsFolderNavigator() {
  document.querySelectorAll(".settings-folder-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const inputId = btn.getAttribute("data-target");
      if (!inputId) return;
      const start = await resolveStartPathForSetting(inputId);
      DJMM.openFolderPicker({
        startPath: start || "~",
        onSelect(path) {
          const inp = document.getElementById(inputId);
          if (inp) inp.value = path;
          scheduleSettingsPageSave();
        },
      });
    });
  });
}

$("#save-settings-btn").addEventListener("click", saveSettings);
$("#cfg-extract-profile").addEventListener("change", updateBitrateVisibility);
loadSettings().then(() => {
  wireThemeControl();
  wirePageBackgroundControl();
  wireSettingsPersistence();
  wireSettingsFolderNavigator();
  scheduleSettingsPageSave();
});
