/* Lossless Check — spectral analysis for detecting lossy transcodes */
(function () {
  "use strict";

  const dirInput = document.getElementById("lc-dir");
  const browseBtn = document.getElementById("lc-browse-btn");
  const chooseFolderBtn = document.getElementById("lc-choose-folder-btn");
  const recursiveChk = document.getElementById("lc-recursive");
  const scanBtn = document.getElementById("lc-scan-btn");
  const scanStatus = document.getElementById("lc-scan-status");
  const resultsCard = document.getElementById("lc-results-card");
  const analyzeBtn = document.getElementById("lc-analyze-btn");
  const saveReportBtn = document.getElementById("lc-save-report-btn");
  const progressWrap = document.getElementById("lc-progress-wrap");
  const progressLabel = document.getElementById("lc-progress-label");
  const progressBar = document.getElementById("lc-progress-bar");
  const summaryDiv = document.getElementById("lc-summary");
  const filterRow = document.getElementById("lc-filter-row");
  const tbody = document.getElementById("lc-results-body");
  const reportsListDiv = document.getElementById("lc-reports-list");

  let scannedFiles = [];
  let results = [];
  let analyzing = false;
  let currentFilter = "all";
  let currentDirectory = "";
  let viewingReport = false;

  function esc(s) {
    const d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
  }

  function fmtDuration(secs) {
    if (!secs || secs <= 0) return "--";
    const m = Math.floor(secs / 60);
    const s = Math.floor(secs % 60);
    return `${m}:${s.toString().padStart(2, "0")}`;
  }

  function fmtSampleRate(sr) {
    if (!sr) return "--";
    return sr >= 1000 ? `${(sr / 1000).toFixed(sr % 1000 ? 1 : 0)} kHz` : `${sr} Hz`;
  }

  function verdictBadge(r) {
    if (!r.verdict) return `<span class="lc-badge lc-badge--pending">Pending</span>`;
    switch (r.verdict) {
      case "lossless":
        return `<span class="lc-badge lc-badge--lossless">Lossless</span>`;
      case "transcode":
        return `<span class="lc-badge lc-badge--transcode">Transcode</span>`;
      case "inconclusive":
        return `<span class="lc-badge lc-badge--inconclusive">Inconclusive</span>`;
      case "error":
        return `<span class="lc-badge lc-badge--error">Error</span>`;
      default:
        return `<span class="lc-badge lc-badge--pending">${esc(r.verdict)}</span>`;
    }
  }

  function confidenceBadge(r) {
    if (!r.confidence) return "--";
    const cls =
      r.confidence === "high" ? "lc-conf--high" :
      r.confidence === "medium" ? "lc-conf--medium" : "lc-conf--low";
    return `<span class="lc-conf ${cls}">${r.confidence}</span>`;
  }

  function renderTable() {
    const filtered = currentFilter === "all"
      ? results
      : results.filter((r) => {
          if (currentFilter === "inconclusive") return r.verdict === "inconclusive" || r.verdict === "error" || !r.verdict;
          return r.verdict === currentFilter;
        });

    tbody.innerHTML = filtered
      .map(
        (r) => `<tr class="lc-row lc-row--${r.verdict || "pending"}" title="${esc(r.reason || "")}">
        <td class="lc-td-name">${esc(r.name)}</td>
        <td class="lc-td-fmt"><span class="format-badge format-badge--${esc(r.ext || "")}">${esc((r.ext || "").toUpperCase())}</span></td>
        <td class="lc-td-sr">${fmtSampleRate(r.sample_rate)}</td>
        <td class="lc-td-dur">${fmtDuration(r.duration)}</td>
        <td class="lc-td-verdict">${verdictBadge(r)}</td>
        <td class="lc-td-bitrate">${r.estimated_bitrate ? esc(r.estimated_bitrate) : "--"}</td>
        <td class="lc-td-cutoff">${r.cutoff_freq ? `${(r.cutoff_freq / 1000).toFixed(1)} kHz` : "--"}</td>
        <td class="lc-td-confidence">${confidenceBadge(r)}</td>
      </tr>`
      )
      .join("");
  }

  function renderSummary() {
    const total = results.length;
    const analyzed = results.filter((r) => r.verdict).length;
    const lossless = results.filter((r) => r.verdict === "lossless").length;
    const transcode = results.filter((r) => r.verdict === "transcode").length;
    const other = results.filter((r) => r.verdict === "inconclusive" || r.verdict === "error").length;
    const pending = total - analyzed;

    let html = `<strong>${total}</strong> files`;
    if (analyzed > 0) {
      html += ` &mdash; <span class="lc-sum-lossless">${lossless} lossless</span>`;
      html += `, <span class="lc-sum-transcode">${transcode} likely transcode${transcode !== 1 ? "s" : ""}</span>`;
      if (other > 0) html += `, <span class="lc-sum-other">${other} inconclusive</span>`;
      if (pending > 0) html += `, ${pending} pending`;
    }
    summaryDiv.innerHTML = html;
    summaryDiv.classList.remove("hidden");

    filterRow.classList.remove("hidden");
    filterRow.style.display = "flex";

    if (analyzed === total && total > 0) {
      saveReportBtn.classList.remove("hidden");
    }
  }

  async function scanFolder() {
    const dir = dirInput.value.trim();
    if (!dir) return;
    const recursive = recursiveChk.checked;

    scanStatus.classList.remove("hidden");
    scanStatus.innerHTML = '<span class="spinner"></span> Scanning...';
    resultsCard.classList.add("hidden");
    saveReportBtn.classList.add("hidden");
    scannedFiles = [];
    results = [];
    viewingReport = false;

    try {
      const resp = await fetch(
        `/api/lossless-check/scan?dir=${encodeURIComponent(dir)}&recursive=${recursive}`
      );
      const data = await resp.json();
      if (data.error) {
        scanStatus.innerHTML = `<span class="error">${esc(data.error)}</span>`;
        return;
      }
      scannedFiles = data.files || [];
      if (scannedFiles.length === 0) {
        scanStatus.innerHTML = "No audio files found in this folder.";
        return;
      }
      scanStatus.innerHTML = `Found <strong>${scannedFiles.length}</strong> audio file${scannedFiles.length !== 1 ? "s" : ""}.`;
      dirInput.value = data.directory;
      currentDirectory = data.directory;

      results = scannedFiles.map((f) => ({
        name: f.name,
        path: f.path,
        ext: f.ext,
        size_mb: f.size_mb,
        verdict: null,
        reason: null,
        cutoff_freq: null,
        estimated_bitrate: null,
        confidence: null,
        sample_rate: null,
        nyquist: null,
        duration: null,
      }));

      resultsCard.classList.remove("hidden");
      analyzeBtn.disabled = false;
      summaryDiv.classList.add("hidden");
      filterRow.classList.add("hidden");
      renderTable();
    } catch (e) {
      scanStatus.innerHTML = `<span class="error">Scan failed: ${esc(e.message)}</span>`;
    }
  }

  async function analyzeAll() {
    if (analyzing || results.length === 0) return;
    analyzing = true;
    analyzeBtn.disabled = true;
    progressWrap.classList.remove("hidden");
    progressWrap.setAttribute("aria-busy", "true");

    const total = results.length;

    for (let i = 0; i < total; i++) {
      const r = results[i];
      progressLabel.textContent = `Analyzing ${i + 1} of ${total}: ${r.name}`;
      progressBar.style.width = `${Math.round((i / total) * 100)}%`;

      try {
        const resp = await fetch("/api/lossless-check/analyze", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ filepath: r.path }),
        });
        const data = await resp.json();
        Object.assign(r, data);
      } catch (e) {
        r.verdict = "error";
        r.reason = e.message;
      }

      renderTable();
      renderSummary();
    }

    progressBar.style.width = "100%";
    progressLabel.textContent = `Done — ${total} files analyzed.`;
    progressWrap.setAttribute("aria-busy", "false");
    analyzing = false;
    analyzeBtn.disabled = false;
  }

  async function saveReport() {
    saveReportBtn.disabled = true;
    saveReportBtn.textContent = "Saving...";
    try {
      const resp = await fetch("/api/lossless-check/report", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ directory: currentDirectory, results }),
      });
      const data = await resp.json();
      if (data.ok) {
        saveReportBtn.textContent = "Saved!";
        loadReportsList();
        setTimeout(() => {
          saveReportBtn.textContent = "Save report";
          saveReportBtn.disabled = false;
        }, 2000);
      }
    } catch (e) {
      saveReportBtn.textContent = "Save failed";
      setTimeout(() => {
        saveReportBtn.textContent = "Save report";
        saveReportBtn.disabled = false;
      }, 2000);
    }
  }

  async function loadReportsList() {
    try {
      const resp = await fetch("/api/lossless-check/reports");
      const reports = await resp.json();
      if (!reports.length) {
        reportsListDiv.innerHTML = '<p class="hint">No saved reports yet. Scan and analyze a folder, then click "Save report".</p>';
        return;
      }
      reportsListDiv.innerHTML = reports.map((r) => {
        const date = r.date ? new Date(r.date).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "";
        const dir = r.directory ? r.directory.split("/").slice(-2).join("/") : "";
        return `<div class="lc-report-item" data-id="${esc(r.id)}">
          <div class="lc-report-info">
            <strong>${esc(dir)}</strong>
            <span class="hint">${date}</span>
          </div>
          <div class="lc-report-stats">
            <span>${r.total} files</span>
            <span class="lc-sum-lossless">${r.lossless} lossless</span>
            <span class="lc-sum-transcode">${r.transcodes} transcode${r.transcodes !== 1 ? "s" : ""}</span>
          </div>
          <div class="lc-report-actions">
            <button type="button" class="btn btn-secondary btn-sm lc-report-load">Load</button>
            <button type="button" class="btn btn-sm sl-remove lc-report-delete" title="Delete report">&#10005;</button>
          </div>
        </div>`;
      }).join("");

      reportsListDiv.querySelectorAll(".lc-report-load").forEach((btn) => {
        btn.addEventListener("click", () => {
          const id = btn.closest(".lc-report-item").dataset.id;
          loadReport(id);
        });
      });

      reportsListDiv.querySelectorAll(".lc-report-delete").forEach((btn) => {
        btn.addEventListener("click", async () => {
          const item = btn.closest(".lc-report-item");
          const id = item.dataset.id;
          btn.disabled = true;
          try {
            await fetch(`/api/lossless-check/report/${encodeURIComponent(id)}`, { method: "DELETE" });
          } catch (_) {}
          item.remove();
          if (!reportsListDiv.querySelector(".lc-report-item")) {
            reportsListDiv.innerHTML = '<p class="hint">No saved reports yet. Scan and analyze a folder, then click "Save report".</p>';
          }
        });
      });
    } catch (e) {
      reportsListDiv.innerHTML = '<p class="hint">Failed to load reports.</p>';
    }
  }

  async function loadReport(id) {
    try {
      const resp = await fetch(`/api/lossless-check/report/${encodeURIComponent(id)}`);
      const report = await resp.json();
      if (report.error) return;

      results = (report.results || []).map((r) => ({
        name: r.name || "",
        path: r.path || r.filepath || "",
        ext: r.ext || (r.name ? r.name.split(".").pop().toLowerCase() : ""),
        size_mb: r.size_mb || null,
        verdict: r.verdict || null,
        reason: r.reason || null,
        cutoff_freq: r.cutoff_freq || null,
        estimated_bitrate: r.estimated_bitrate || null,
        confidence: r.confidence || null,
        sample_rate: r.sample_rate || null,
        nyquist: r.nyquist || null,
        duration: r.duration || null,
      }));

      currentDirectory = report.directory || "";
      viewingReport = true;

      const date = report.date ? new Date(report.date).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "";
      scanStatus.classList.remove("hidden");
      scanStatus.innerHTML = `Loaded report from <strong>${esc(date)}</strong> &mdash; ${esc(currentDirectory)}`;
      if (currentDirectory) dirInput.value = currentDirectory;

      resultsCard.classList.remove("hidden");
      analyzeBtn.disabled = true;
      progressWrap.classList.add("hidden");
      saveReportBtn.classList.add("hidden");
      currentFilter = "all";
      filterRow.querySelectorAll(".lc-filter").forEach((b) => b.classList.remove("active"));
      filterRow.querySelector('[data-filter="all"]')?.classList.add("active");

      renderTable();
      renderSummary();
    } catch (e) {
      scanStatus.classList.remove("hidden");
      scanStatus.innerHTML = `<span class="error">Failed to load report: ${esc(e.message)}</span>`;
    }
  }

  scanBtn.addEventListener("click", scanFolder);
  analyzeBtn.addEventListener("click", analyzeAll);
  saveReportBtn.addEventListener("click", saveReport);

  browseBtn.addEventListener("click", () => {
    const dir = dirInput.value.trim();
    if (dir) scanFolder();
  });

  dirInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") scanFolder();
  });

  chooseFolderBtn.addEventListener("click", async () => {
    let start = dirInput.value.trim();
    if (!start) {
      try {
        const resp = await fetch("/api/settings");
        const cfg = await resp.json();
        start = (cfg.destination_dir || "").trim() || "~";
      } catch (_) {
        start = "~";
      }
    }
    DJMM.openFolderPicker({
      startPath: start,
      onSelect(path) {
        dirInput.value = path;
      },
    });
  });

  filterRow.addEventListener("click", (e) => {
    const btn = e.target.closest(".lc-filter");
    if (!btn) return;
    currentFilter = btn.dataset.filter;
    filterRow.querySelectorAll(".lc-filter").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    renderTable();
  });

  loadReportsList();
})();
