/* Capture Playlist — client-side logic */

(function () {
  "use strict";

  // DOM refs
  const playlistSelect = document.getElementById("cap-playlist");
  const refreshBtn = document.getElementById("cap-refresh-btn");
  const playlistInfo = document.getElementById("cap-playlist-info");
  const trackPreview = document.getElementById("cap-track-preview");
  const trackTbody = document.getElementById("cap-track-tbody");
  const outputDir = document.getElementById("cap-output-dir");
  const preflightBtn = document.getElementById("cap-preflight-btn");
  const testSignalBtn = document.getElementById("cap-test-signal-btn");
  const preflightResults = document.getElementById("cap-preflight-results");
  const preflightList = document.getElementById("cap-preflight-list");
  const startBtn = document.getElementById("cap-start-btn");

  const setupCard = document.getElementById("cap-setup-card");
  const runningCard = document.getElementById("cap-running-card");
  const reviewCard = document.getElementById("cap-review-card");

  const curTitle = document.getElementById("cap-cur-title");
  const curDetail = document.getElementById("cap-cur-detail");
  const progressBar = document.getElementById("cap-progress-bar");
  const statCompleted = document.getElementById("cap-stat-completed");
  const statFailed = document.getElementById("cap-stat-failed");
  const statPending = document.getElementById("cap-stat-pending");
  const statEta = document.getElementById("cap-stat-eta");
  const queueTbody = document.getElementById("cap-queue-tbody");

  const pauseBtn = document.getElementById("cap-pause-btn");
  const stopBtn = document.getElementById("cap-stop-btn");
  const emergencyBtn = document.getElementById("cap-emergency-btn");

  const reviewSummary = document.getElementById("cap-review-summary");
  const reviewTbody = document.getElementById("cap-review-tbody");
  const resumeBtn = document.getElementById("cap-resume-btn");
  const fixArtworkBtn = document.getElementById("cap-fix-artwork-btn");
  const fixArtworkResult = document.getElementById("cap-fix-artwork-result");
  const newBtn = document.getElementById("cap-new-btn");

  // State
  let snapshotTracks = [];
  let activeSessionId = null;
  let pollTimer = null;
  let captureBackend = "obs";  // set from config in loadDefaults()

  // ------------------------------------------------------------------
  // Playlists
  // ------------------------------------------------------------------

  async function loadPlaylists() {
    playlistSelect.innerHTML = '<option value="">Loading…</option>';
    try {
      const resp = await fetch("/api/capture/playlists");
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        playlistSelect.innerHTML = '<option value="">(Error loading playlists)</option>';
        playlistInfo.textContent = err.error || "Failed to load playlists";
        return;
      }
      const list = await resp.json();
      playlistSelect.innerHTML = '<option value="">Select a Music playlist…</option>';
      list.forEach((p) => {
        const opt = document.createElement("option");
        opt.value = p.persistent_id;
        const dur = formatDuration(p.total_duration_seconds || 0);
        opt.textContent = `${p.name} (${p.track_count} tracks, ${dur})`;
        opt.dataset.name = p.name;
        playlistSelect.appendChild(opt);
      });
      preflightBtn.disabled = false;
      testSignalBtn.disabled = false;
    } catch (e) {
      playlistSelect.innerHTML = '<option value="">(Error)</option>';
      playlistInfo.textContent = e.message;
    }
  }

  async function loadSnapshot() {
    const pid = playlistSelect.value;
    if (!pid) {
      trackPreview.style.display = "none";
      playlistInfo.textContent = "";
      snapshotTracks = [];
      startBtn.disabled = true;
      return;
    }

    playlistInfo.textContent = "Loading track list…";
    try {
      const resp = await fetch("/api/capture/snapshot", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ playlist_persistent_id: pid }),
      });
      const data = await resp.json();
      snapshotTracks = data.tracks || [];
      const totalDur = snapshotTracks.reduce((s, t) => s + (t.duration_seconds || 0), 0);
      playlistInfo.textContent = `${snapshotTracks.length} tracks, ${formatDuration(totalDur)} total`;
      renderTrackPreview();
    } catch (e) {
      playlistInfo.textContent = "Error: " + e.message;
    }
  }

  function renderTrackPreview() {
    trackTbody.innerHTML = "";
    if (snapshotTracks.length === 0) {
      trackPreview.style.display = "none";
      return;
    }
    trackPreview.style.display = "";
    snapshotTracks.forEach((t) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `<td>${t.ordinal + 1}</td><td>${esc(t.title)}</td><td>${esc(t.artist)}</td><td>${esc(t.album)}</td><td>${formatDuration(t.duration_seconds)}</td>`;
      trackTbody.appendChild(tr);
    });
  }

  // ------------------------------------------------------------------
  // Preflight
  // ------------------------------------------------------------------

  async function runPreflight(testSignal) {
    preflightResults.style.display = "";
    preflightList.innerHTML = "<li>Running checks…</li>";
    startBtn.disabled = true;

    try {
      const resp = await fetch("/api/capture/preflight", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ test_signal: !!testSignal }),
      });
      const data = await resp.json();
      preflightList.innerHTML = "";
      data.checks.forEach((c) => {
        const li = document.createElement("li");
        li.className = c.ok ? "check-pass" : "check-fail";
        li.textContent = c.name;
        if (!c.ok && c.fix) {
          const fix = document.createElement("span");
          fix.className = "check-fix";
          fix.textContent = " — " + c.fix;
          li.appendChild(fix);
        }
        preflightList.appendChild(li);
      });

      if (data.ok && snapshotTracks.length > 0 && playlistSelect.value) {
        startBtn.disabled = false;
      }
    } catch (e) {
      preflightList.innerHTML = `<li class="check-fail">Error: ${esc(e.message)}</li>`;
    }
  }

  // ------------------------------------------------------------------
  // Session control
  // ------------------------------------------------------------------

  async function startCapture() {
    if (!playlistSelect.value || snapshotTracks.length === 0) return;

    startBtn.disabled = true;
    const selectedOpt = playlistSelect.options[playlistSelect.selectedIndex];

    try {
      const resp = await fetch("/api/capture/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          playlist_persistent_id: playlistSelect.value,
          playlist_name: selectedOpt.dataset.name || "",
          tracks: snapshotTracks,
          output_dir: outputDir.value,
          backend: captureBackend,
        }),
      });
      const data = await resp.json();
      if (!resp.ok) {
        alert("Error: " + (data.error || "Failed to start"));
        startBtn.disabled = false;
        return;
      }
      activeSessionId = data.session_id;
      showCard("running");
      startPolling();
    } catch (e) {
      alert("Error: " + e.message);
      startBtn.disabled = false;
    }
  }

  function startPolling() {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(pollSession, 1000);
    pollSession();
  }

  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  async function pollSession() {
    if (!activeSessionId) return;
    try {
      const resp = await fetch(`/api/capture/sessions/${activeSessionId}`);
      if (!resp.ok) return;
      const s = await resp.json();
      renderRunning(s);

      const terminal = ["completed", "failed", "cancelled"];
      const pausable = ["paused", "needs_attention"];
      if (terminal.includes(s.status) || pausable.includes(s.status)) {
        stopPolling();
        showReview(s);
      }
    } catch (e) {
      // Transient network error, keep polling
    }
  }

  function renderRunning(s) {
    const tracks = s.tracks || [];
    const total = tracks.length;
    const completed = tracks.filter((t) => t.status === "completed").length;
    const failed = tracks.filter((t) => t.status === "failed").length;
    const pending = tracks.filter(
      (t) => t.status === "pending" || t.status === "arming" || t.status === "recording"
    ).length;

    const current = tracks.find(
      (t) => t.status === "arming" || t.status === "recording" || t.status === "stopping" ||
             t.status === "converting" || t.status === "verifying" || t.status === "tagging"
    );

    if (current) {
      curTitle.textContent = `${current.title} — ${current.artist}`;
      curDetail.textContent = `Track ${current.ordinal + 1} of ${total} · ${current.status}`;
    } else {
      curTitle.textContent = s.status === "running" ? "Preparing…" : s.status;
      curDetail.textContent = "";
    }

    const pct = total > 0 ? ((completed / total) * 100).toFixed(1) : 0;
    progressBar.style.width = pct + "%";

    statCompleted.textContent = completed + " completed";
    statFailed.textContent = failed + " failed";
    statPending.textContent = pending + " pending";

    if (completed > 0 && pending > 0) {
      const avgDur = tracks
        .filter((t) => t.status === "completed")
        .reduce((s, t) => s + (t.duration_seconds || 0), 0) / completed;
      const eta = pending * avgDur;
      statEta.textContent = "~" + formatDuration(eta) + " remaining";
    } else {
      statEta.textContent = "";
    }

    renderQueue(tracks, queueTbody, false);
  }

  function renderQueue(tracks, tbody, showActions) {
    tbody.innerHTML = "";
    tracks.forEach((t) => {
      const tr = document.createElement("tr");
      const statusClass = statusBadgeClass(t.status);
      let actions = "";
      if (showActions) {
        if (t.status === "failed" || t.status === "needs_review") {
          actions = `<button class="btn btn-xs" onclick="captureRetry(${t.ordinal})">Retry</button> <button class="btn btn-xs" onclick="captureSkip(${t.ordinal})">Skip</button>`;
        }
      }
      tr.innerHTML = `<td>${t.ordinal + 1}</td><td>${esc(t.title)}</td><td>${esc(t.artist)}</td><td><span class="badge ${statusClass}">${t.status}</span></td>${showActions ? "<td>" + actions + "</td>" : ""}`;
      tbody.appendChild(tr);
    });
  }

  function showReview(s) {
    const tracks = s.tracks || [];
    const completed = tracks.filter((t) => t.status === "completed").length;
    const failed = tracks.filter((t) => t.status === "failed").length;
    const skipped = tracks.filter((t) => t.status === "skipped").length;
    const pending = tracks.filter((t) => t.status === "pending").length;

    reviewSummary.innerHTML = `<span>${completed} completed</span><span>${failed} failed</span><span>${skipped} skipped</span><span>${pending} pending</span><span>Session: ${s.status}</span>`;
    renderQueue(tracks, reviewTbody, true);

    const canResume = s.status === "paused" || s.status === "needs_attention";
    resumeBtn.style.display = canResume ? "" : "none";

    showCard("review");
  }

  async function pauseCapture() {
    if (!activeSessionId) return;
    await fetch(`/api/capture/sessions/${activeSessionId}/pause`, { method: "POST" });
  }

  async function stopCapture() {
    if (!activeSessionId) return;
    await fetch(`/api/capture/sessions/${activeSessionId}/stop`, { method: "POST" });
  }

  async function emergencyStop() {
    if (!activeSessionId) return;
    if (!confirm("Emergency stop will interrupt the current track. Continue?")) return;
    await fetch(`/api/capture/sessions/${activeSessionId}/emergency-stop`, { method: "POST" });
    stopPolling();
    setTimeout(pollSession, 500);
  }

  async function resumeCapture() {
    if (!activeSessionId) return;
    const resp = await fetch(`/api/capture/sessions/${activeSessionId}/resume`, { method: "POST" });
    if (resp.ok) {
      showCard("running");
      startPolling();
    } else {
      const data = await resp.json().catch(() => ({}));
      alert("Error: " + (data.error || "Failed to resume"));
    }
  }

  let fixArtworkPoll = null;

  function showFixArtworkNote(text, tone) {
    // tone: "info" | "ok" | "warn" | "err"
    const colors = { info: "var(--fg, #ddd)", ok: "#3fb950", warn: "#d29922", err: "#f85149" };
    fixArtworkResult.textContent = text;
    fixArtworkResult.style.color = colors[tone] || colors.info;
    fixArtworkResult.style.display = "";
  }

  function renderFixArtworkStatus(st) {
    const f = (st.fixed || []).length;
    const s = (st.skipped || []).length;
    const x = (st.failed || []).length;
    if (st.running) {
      const cur = st.current ? ` — ${st.current}` : "";
      showFixArtworkNote(`⏳ Fixing artwork… ${st.done}/${st.total}${cur}`, "info");
      return;
    }
    // finished
    if (st.error) {
      showFixArtworkNote(`Error: ${st.error}`, "err");
      return;
    }
    let msg = `✓ Artwork re-applied to ${f} track${f === 1 ? "" : "s"}.`;
    if (s) msg += ` ${s} skipped (file not found).`;
    if (x) msg += ` ${x} failed (no artwork from Music).`;
    showFixArtworkNote(msg, x || s ? "warn" : "ok");
  }

  async function pollFixArtwork() {
    try {
      const resp = await fetch(`/api/capture/sessions/${activeSessionId}/fix-artwork/status`);
      if (!resp.ok) return;
      const st = await resp.json();
      renderFixArtworkStatus(st);
      if (!st.running) {
        clearInterval(fixArtworkPoll);
        fixArtworkPoll = null;
        fixArtworkBtn.disabled = false;
        fixArtworkBtn.textContent = "Fix artwork";
      }
    } catch (e) {
      // keep polling; transient
    }
  }

  async function fixArtwork() {
    if (!activeSessionId || fixArtworkPoll) return;
    fixArtworkBtn.disabled = true;
    fixArtworkBtn.textContent = "Fixing artwork…";
    showFixArtworkNote("⏳ Starting…", "info");
    try {
      const resp = await fetch(`/api/capture/sessions/${activeSessionId}/fix-artwork`, { method: "POST" });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        // 409 means a job is already running — just attach to it by polling.
        if (resp.status !== 409) {
          showFixArtworkNote("Error: " + (data.error || "Failed to start"), "err");
          fixArtworkBtn.disabled = false;
          fixArtworkBtn.textContent = "Fix artwork";
          return;
        }
      }
      showFixArtworkNote(`⏳ Fixing artwork… 0/${data.total ?? "?"}`, "info");
      fixArtworkPoll = setInterval(pollFixArtwork, 600);
      pollFixArtwork();
    } catch (e) {
      showFixArtworkNote("Error: " + e, "err");
      fixArtworkBtn.disabled = false;
      fixArtworkBtn.textContent = "Fix artwork";
    }
  }

  function newCapture() {
    activeSessionId = null;
    stopPolling();
    snapshotTracks = [];
    trackPreview.style.display = "none";
    preflightResults.style.display = "none";
    startBtn.disabled = true;
    showCard("setup");
    loadPlaylists();
  }

  // ------------------------------------------------------------------
  // Retry / Skip (exposed globally for inline onclick)
  // ------------------------------------------------------------------

  window.captureRetry = async function (ordinal) {
    if (!activeSessionId) return;
    await fetch(`/api/capture/sessions/${activeSessionId}/tracks/${ordinal}/retry`, { method: "POST" });
    pollSession();
  };

  window.captureSkip = async function (ordinal) {
    if (!activeSessionId) return;
    await fetch(`/api/capture/sessions/${activeSessionId}/tracks/${ordinal}/skip`, { method: "POST" });
    pollSession();
  };

  // ------------------------------------------------------------------
  // UI helpers
  // ------------------------------------------------------------------

  function showCard(which) {
    setupCard.style.display = which === "setup" ? "" : "none";
    runningCard.style.display = which === "running" ? "" : "none";
    reviewCard.style.display = which === "review" ? "" : "none";
  }

  function formatDuration(sec) {
    if (!sec || sec < 0) return "0:00";
    const m = Math.floor(sec / 60);
    const s = Math.floor(sec % 60);
    return m + ":" + String(s).padStart(2, "0");
  }

  function esc(s) {
    if (!s) return "";
    const d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
  }

  function statusBadgeClass(status) {
    switch (status) {
      case "completed": return "badge-ok";
      case "failed": return "badge-err";
      case "recording":
      case "arming": return "badge-active";
      case "skipped": return "badge-skip";
      default: return "badge-pending";
    }
  }

  // ------------------------------------------------------------------
  // Recovery check on page load
  // ------------------------------------------------------------------

  async function checkRecoverable() {
    try {
      const resp = await fetch("/api/capture/recoverable");
      if (!resp.ok) return;
      const sessions = await resp.json();
      if (sessions.length > 0) {
        const s = sessions[0];
        const resumeIt = confirm(
          `A previous capture session was interrupted (${s.tracks ? s.tracks.length : "?"} tracks, status: ${s.status}).\n\nRecover and review it?`
        );
        if (resumeIt) {
          const resp2 = await fetch(`/api/capture/recover/${s.session_id}`, { method: "POST" });
          if (resp2.ok) {
            const data = await resp2.json();
            activeSessionId = s.session_id;
            if (data.session) showReview(data.session);
          }
        }
      }
    } catch (e) {
      // Ignore
    }
  }

  // ------------------------------------------------------------------
  // Settings default
  // ------------------------------------------------------------------

  async function loadDefaults() {
    try {
      const resp = await fetch("/api/settings");
      if (resp.ok) {
        const cfg = await resp.json();
        captureBackend = cfg.capture?.backend || "obs";
        if (!outputDir.value) {
          outputDir.value = cfg.capture?.output_dir || cfg.destination_dir || "";
        }
      }
    } catch (e) {
      // Ignore
    }
  }

  // ------------------------------------------------------------------
  // Event bindings
  // ------------------------------------------------------------------

  refreshBtn.addEventListener("click", loadPlaylists);
  playlistSelect.addEventListener("change", loadSnapshot);
  preflightBtn.addEventListener("click", () => runPreflight(false));
  testSignalBtn.addEventListener("click", () => runPreflight(true));
  startBtn.addEventListener("click", startCapture);
  pauseBtn.addEventListener("click", pauseCapture);
  stopBtn.addEventListener("click", stopCapture);
  emergencyBtn.addEventListener("click", emergencyStop);
  resumeBtn.addEventListener("click", resumeCapture);
  fixArtworkBtn.addEventListener("click", fixArtwork);
  newBtn.addEventListener("click", newCapture);

  // ------------------------------------------------------------------
  // Folder picker for output dir
  // ------------------------------------------------------------------

  document.getElementById("cap-output-dir-browse").addEventListener("click", () => {
    const start = outputDir.value.trim() || "~/Music/playlist_recordings";
    if (typeof DJMM !== "undefined" && DJMM.openFolderPicker) {
      DJMM.openFolderPicker({
        startPath: start,
        onSelect(path) { outputDir.value = path; },
      });
    }
  });

  // ------------------------------------------------------------------
  // Init
  // ------------------------------------------------------------------

  loadDefaults();
  loadPlaylists();
  checkRecoverable();
})();
