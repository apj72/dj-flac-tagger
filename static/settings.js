const $ = (sel) => document.querySelector(sel);

async function loadSettings() {
  const resp = await fetch("/api/settings");
  const cfg = await resp.json();
  $("#cfg-source").value = cfg.source_dir || "";
  $("#cfg-dest").value = cfg.destination_dir || "";
  $("#cfg-pn-app").value = cfg.platinum_notes_app || "";
  $("#cfg-pn-suffix").value = cfg.pn_output_suffix || "_PN";
  $("#cfg-target-lufs").value =
    cfg.target_lufs !== undefined && cfg.target_lufs !== null ? String(cfg.target_lufs) : "-14";
  $("#cfg-target-tp").value =
    cfg.target_true_peak !== undefined && cfg.target_true_peak !== null
      ? String(cfg.target_true_peak)
      : "-1";
}

async function saveSettings() {
  const resp = await fetch("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      source_dir: $("#cfg-source").value.trim(),
      destination_dir: $("#cfg-dest").value.trim(),
      platinum_notes_app: $("#cfg-pn-app").value.trim(),
      pn_output_suffix: $("#cfg-pn-suffix").value.trim() || "_PN",
      target_lufs: $("#cfg-target-lufs").value.trim(),
      target_true_peak: $("#cfg-target-tp").value.trim(),
    }),
  });
  await resp.json();

  const status = $("#settings-status");
  status.classList.remove("hidden");
  setTimeout(() => status.classList.add("hidden"), 2000);
}

$("#save-settings-btn").addEventListener("click", saveSettings);
loadSettings();
