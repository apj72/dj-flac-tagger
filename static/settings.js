const $ = (sel) => document.querySelector(sel);

function collectSettingsPageDraft() {
  return {
    v: 1,
    source_dir: $("#cfg-source").value,
    destination_dir: $("#cfg-dest").value,
    fix_metadata_default_dir: $("#cfg-fix-default").value,
    inspect_default_dir: $("#cfg-inspect-default").value,
    extract_profile: $("#cfg-extract-profile").value,
    platinum_notes_app: $("#cfg-pn-app").value,
    pn_output_suffix: $("#cfg-pn-suffix").value,
    target_lufs: $("#cfg-target-lufs").value,
    target_true_peak: $("#cfg-target-tp").value,
    loudness_verify_enabled: $("#cfg-loudness-verify").checked,
  };
}

function scheduleSettingsPageSave() {
  if (typeof djmmPageStateSchedule === "function") {
    djmmPageStateSchedule("settings", collectSettingsPageDraft);
  }
}

function applySettingsDraft(st) {
  if (st.source_dir != null) $("#cfg-source").value = st.source_dir;
  if (st.destination_dir != null) $("#cfg-dest").value = st.destination_dir;
  if (st.fix_metadata_default_dir != null) $("#cfg-fix-default").value = st.fix_metadata_default_dir;
  if (st.inspect_default_dir != null) $("#cfg-inspect-default").value = st.inspect_default_dir;
  if (st.extract_profile != null) {
    const sel = $("#cfg-extract-profile");
    if ([...sel.options].some((o) => o.value === st.extract_profile)) sel.value = st.extract_profile;
  }
  if (st.platinum_notes_app != null) $("#cfg-pn-app").value = st.platinum_notes_app;
  if (st.pn_output_suffix != null) $("#cfg-pn-suffix").value = st.pn_output_suffix;
  if (st.target_lufs != null) $("#cfg-target-lufs").value = st.target_lufs;
  if (st.target_true_peak != null) $("#cfg-target-tp").value = st.target_true_peak;
  if (st.loudness_verify_enabled != null) $("#cfg-loudness-verify").checked = st.loudness_verify_enabled;
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
  $("#cfg-source").value = cfg.source_dir || "";
  $("#cfg-dest").value = cfg.destination_dir || "";
  $("#cfg-fix-default").value = cfg.fix_metadata_default_dir || "";
  $("#cfg-inspect-default").value = cfg.inspect_default_dir || "";
  $("#cfg-pn-app").value = cfg.platinum_notes_app || "";
  $("#cfg-pn-suffix").value = cfg.pn_output_suffix || "_PN";
  $("#cfg-target-lufs").value =
    cfg.target_lufs !== undefined && cfg.target_lufs !== null ? String(cfg.target_lufs) : "-14";
  $("#cfg-target-tp").value =
    cfg.target_true_peak !== undefined && cfg.target_true_peak !== null
      ? String(cfg.target_true_peak)
      : "-1";
  $("#cfg-loudness-verify").checked = cfg.loudness_verify_enabled !== false;
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
      extract_profile: $("#cfg-extract-profile").value,
      platinum_notes_app: $("#cfg-pn-app").value.trim(),
      pn_output_suffix: $("#cfg-pn-suffix").value.trim() || "_PN",
      target_lufs: $("#cfg-target-lufs").value.trim(),
      target_true_peak: $("#cfg-target-tp").value.trim(),
      loudness_verify_enabled: $("#cfg-loudness-verify").checked,
    }),
  });
  await resp.json();

  if (typeof djmmPageStateSetPage === "function") {
    djmmPageStateSetPage("settings", null);
  }

  const status = $("#settings-status");
  status.classList.remove("hidden");
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

function wireSettingsPersistence() {
  [
    "cfg-source",
    "cfg-dest",
    "cfg-fix-default",
    "cfg-inspect-default",
    "cfg-extract-profile",
    "cfg-pn-app",
    "cfg-pn-suffix",
    "cfg-target-lufs",
    "cfg-target-tp",
  ].forEach((id) => {
    document.getElementById(id)?.addEventListener("input", scheduleSettingsPageSave);
    document.getElementById(id)?.addEventListener("change", scheduleSettingsPageSave);
  });
  document.getElementById("cfg-loudness-verify")?.addEventListener("change", scheduleSettingsPageSave);
}

$("#save-settings-btn").addEventListener("click", saveSettings);
loadSettings().then(() => {
  wireThemeControl();
  wireSettingsPersistence();
  scheduleSettingsPageSave();
});
