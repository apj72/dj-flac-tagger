/**
 * Bottom preview player: manual play/pause, draggable timeline, buffer hint.
 * Depends on GET /api/stream-audio?path=…
 */
(function () {
  const PATH_OK = /\.(flac|mp3|m4a|mp4|aac|ogg|oga|wav|aiff|aif|wma)$/i;

  let audio = null;
  let els = {};
  let lastPath = "";
  let dragging = false;
  let pendingSeekPct = null;

  function fmtTime(sec) {
    if (!Number.isFinite(sec) || sec < 0) return "0:00";
    const m = Math.floor(sec / 60);
    const s = Math.floor(sec % 60);
    return `${m}:${String(s).padStart(2, "0")}`;
  }

  function durationSafe() {
    const d = audio.duration;
    return Number.isFinite(d) && d > 0 ? d : 0;
  }

  function syncTransportButtons() {
    const ok = !!(audio.src && PATH_OK.test(lastPath));
    const dur = durationSafe();
    const playing = !audio.paused && !audio.ended;
    els.playBtn.disabled = !ok || playing;
    els.pauseBtn.disabled = !ok || !playing;
  }

  function setTimelineUi(pct01, elapsedSec) {
    const p = Math.max(0, Math.min(100, pct01 * 100));
    els.filled.style.width = `${p}%`;
    els.thumb.style.left = `${p}%`;
    els.rail.setAttribute("aria-valuenow", String(Math.round(p)));
    const dur = durationSafe();
    if (Number.isFinite(elapsedSec)) {
      els.timeElapsed.textContent = fmtTime(elapsedSec);
    } else if (dur > 0) {
      els.timeElapsed.textContent = fmtTime((pct01 * dur));
    } else {
      els.timeElapsed.textContent = fmtTime(0);
    }
  }

  function syncFromAudio() {
    if (dragging) return;
    const dur = durationSafe();
    if (!dur) {
      setTimelineUi(0, 0);
      els.timeTotal.textContent = "0:00";
      if (els.buffer) els.buffer.style.width = "0%";
      return;
    }
    if (audio.ended) {
      setTimelineUi(1, dur);
    } else {
      const t = Math.min(Math.max(0, audio.currentTime), dur);
      setTimelineUi(t / dur, t);
    }
    els.timeTotal.textContent = fmtTime(dur);
  }

  function updateBuffered() {
    const dur = durationSafe();
    if (!dur || !els.buffer) return;
    const ranges = audio.buffered;
    if (!ranges.length) {
      els.buffer.style.width = "0%";
      return;
    }
    let maxEnd = 0;
    for (let i = 0; i < ranges.length; i += 1) {
      maxEnd = Math.max(maxEnd, ranges.end(i));
    }
    els.buffer.style.width = `${Math.min(100, (maxEnd / dur) * 100)}%`;
  }

  function flushPendingSeek() {
    if (pendingSeekPct == null) return;
    if (!durationSafe()) return;
    seekToPct(pendingSeekPct);
    pendingSeekPct = null;
    updateBuffered();
  }

  function pctFromClientX(clientX) {
    const r = els.rail.getBoundingClientRect();
    return Math.max(0, Math.min(1, (clientX - r.left) / Math.max(r.width, 1)));
  }

  function seekToPct(pct01) {
    const dur = durationSafe();
    if (!dur) return;
    audio.currentTime = pct01 * dur;
    setTimelineUi(pct01, pct01 * dur);
  }

  function beginDrag(ev) {
    if (!ev.isPrimary) return;
    if (!audio.src || !durationSafe()) return;
    ev.preventDefault();
    dragging = true;
    els.rail.classList.add("djmm-dragging");
    try {
      els.rail.setPointerCapture(ev.pointerId);
    } catch (_) {
      /* ignore */
    }
    const p = pctFromClientX(ev.clientX);
    seekToPct(p);
  }

  function moveDrag(ev) {
    if (!dragging) return;
    if (!durationSafe()) return;
    const dragPct = pctFromClientX(ev.clientX);
    const dur = durationSafe();
    if (dur > 0) {
      setTimelineUi(dragPct, dragPct * dur);
      audio.currentTime = dragPct * dur;
    }
  }

  function endDrag(ev) {
    if (!dragging) return;
    dragging = false;
    els.rail.classList.remove("djmm-dragging");
    try {
      els.rail.releasePointerCapture(ev.pointerId);
    } catch (_) {
      /* not captured */
    }
    if (durationSafe()) {
      seekToPct(pctFromClientX(ev.clientX));
    }
    syncFromAudio();
    syncTransportButtons();
  }

  function build() {
    if (document.getElementById("djmm-player-bar")) return;
    document.body.classList.add("has-djmm-player");
    const wrap = document.createElement("div");
    wrap.id = "djmm-player-bar";
    wrap.className = "djmm-player-bar";
    wrap.setAttribute("role", "region");
    wrap.setAttribute("aria-label", "Audio preview");
    wrap.innerHTML = `
      <div class="djmm-player-inner">
        <div class="djmm-player-transport" aria-label="Playback">
          <button type="button" class="djmm-player-play-btn btn btn-accent btn-sm" disabled
            aria-label="Play">Play</button>
          <button type="button" class="djmm-player-pause-btn btn btn-secondary btn-sm" disabled
            aria-label="Pause">Pause</button>
        </div>
        <div class="djmm-player-meta">
          <div class="djmm-player-title" id="djmm-player-title">No track loaded — select an audio file above</div>
          <div class="djmm-player-row">
            <span class="djmm-player-time mono djmm-player-time-elapsed" id="djmm-time-elapsed">0:00</span>
            <div class="djmm-player-rail-track">
              <div class="djmm-player-rail"
                id="djmm-rail"
                role="slider"
                tabindex="0"
                title="Seek: click, drag, arrow keys, Home/End. Space: play or pause."
                aria-label="Seek position"
                aria-valuemin="0"
                aria-valuemax="100"
                aria-valuenow="0">
                <div class="djmm-player-track-bg"></div>
                <div class="djmm-player-buffer" id="djmm-buffer"></div>
                <div class="djmm-player-filled" id="djmm-filled"></div>
                <div class="djmm-player-thumb" id="djmm-thumb"></div>
              </div>
            </div>
            <span class="djmm-player-time mono djmm-player-time-total" id="djmm-time-total">0:00</span>
          </div>
        </div>
        <label class="djmm-player-vol-label" title="Volume">
          <span class="sr-only">Volume</span>
          <input type="range" id="djmm-player-volume" min="0" max="1" step="0.05" value="0.9" />
        </label>
      </div>
    `;
    document.body.appendChild(wrap);

    audio = new Audio();
    audio.preload = "metadata";

    els.titleEl = document.getElementById("djmm-player-title");
    els.playBtn = wrap.querySelector(".djmm-player-play-btn");
    els.pauseBtn = wrap.querySelector(".djmm-player-pause-btn");
    els.rail = document.getElementById("djmm-rail");
    els.filled = document.getElementById("djmm-filled");
    els.buffer = document.getElementById("djmm-buffer");
    els.thumb = document.getElementById("djmm-thumb");
    els.timeElapsed = document.getElementById("djmm-time-elapsed");
    els.timeTotal = document.getElementById("djmm-time-total");
    els.vol = document.getElementById("djmm-player-volume");

    function applyVolume() {
      const n = parseFloat(els.vol.value);
      if (!Number.isNaN(n)) audio.volume = Math.max(0, Math.min(1, n));
    }

    try {
      const v = localStorage.getItem("djmmPlayerVolume");
      if (v != null) {
        const n = parseFloat(v);
        if (!Number.isNaN(n)) {
          els.vol.value = String(Math.max(0, Math.min(1, n)));
        }
      }
    } catch (_) {
      /* ignore */
    }
    applyVolume();

    els.playBtn.addEventListener("click", () => {
      if (!audio.src || els.playBtn.disabled) return;
      void audio.play().catch(() => {});
    });

    els.pauseBtn.addEventListener("click", () => {
      if (!audio.src || els.pauseBtn.disabled) return;
      audio.pause();
    });

    els.vol.addEventListener("input", () => {
      applyVolume();
      try {
        localStorage.setItem("djmmPlayerVolume", els.vol.value);
      } catch (_) {
        /* ignore */
      }
    });

    audio.addEventListener("timeupdate", syncFromAudio);
    audio.addEventListener("durationchange", () => {
      syncFromAudio();
      updateBuffered();
    });
    audio.addEventListener("loadedmetadata", () => {
      flushPendingSeek();
      syncFromAudio();
      updateBuffered();
      syncTransportButtons();
    });

    audio.addEventListener("play", syncTransportButtons);
    audio.addEventListener("pause", syncTransportButtons);
    audio.addEventListener("playing", syncTransportButtons);
    audio.addEventListener("waiting", syncTransportButtons);
    audio.addEventListener("ended", () => {
      syncFromAudio();
      syncTransportButtons();
    });

    audio.addEventListener("progress", updateBuffered);

    audio.addEventListener("error", () => {
      els.titleEl.textContent = "Could not load this file in the browser preview";
      els.playBtn.disabled = true;
      els.pauseBtn.disabled = true;
    });

    /* Timeline: drag with pointer; click without full drag still seeks */
    els.rail.addEventListener("pointerdown", (ev) => {
      if (!ev.isPrimary || !audio.src) return;
      if (!durationSafe()) {
        ev.preventDefault();
        pendingSeekPct = pctFromClientX(ev.clientX);
        const p = pendingSeekPct * 100;
        els.filled.style.width = `${p}%`;
        els.thumb.style.left = `${p}%`;
        els.timeElapsed.textContent = "…";
        return;
      }
      beginDrag(ev);
    });
    els.rail.addEventListener("pointermove", moveDrag);
    els.rail.addEventListener("pointerup", endDrag);
    els.rail.addEventListener("pointercancel", endDrag);

    els.rail.addEventListener("keydown", (e) => {
      const dur = durationSafe();
      if (!dur) return;
      const step = e.shiftKey ? 15 : 5;
      if (e.key === "ArrowRight") {
        e.preventDefault();
        seekToPct(Math.min(1, audio.currentTime / dur + step / dur));
      } else if (e.key === "ArrowLeft") {
        e.preventDefault();
        seekToPct(Math.max(0, audio.currentTime / dur - step / dur));
      } else if (e.key === "Home") {
        e.preventDefault();
        seekToPct(0);
      } else if (e.key === "End") {
        e.preventDefault();
        seekToPct(1);
      } else if (e.key === " " || e.code === "Space") {
        e.preventDefault();
        if (!audio.src || !durationSafe()) return;
        if (audio.paused) void audio.play().catch(() => {});
        else audio.pause();
      }
    });

    window.DJMM = window.DJMM || {};
    window.DJMM.setPlayerTrack = function (path, title) {
      if (!path || typeof path !== "string") return;
      if (!PATH_OK.test(path)) {
        audio.pause();
        audio.removeAttribute("src");
        audio.load();
        lastPath = "";
        els.playBtn.disabled = true;
        els.pauseBtn.disabled = true;
        pendingSeekPct = null;
        setTimelineUi(0, 0);
        els.buffer.style.width = "0%";
        els.titleEl.textContent = title || path.split("/").pop() || "Track";
        els.timeElapsed.textContent = "—";
        els.timeTotal.textContent = "(preview not supported for this type)";
        return;
      }

      const label = (title && String(title).trim()) || path.split("/").pop() || "Track";
      els.titleEl.textContent = label;

      pendingSeekPct = null;
      dragging = false;
      els.rail.classList.remove("djmm-dragging");

      if (lastPath === path && audio.src) {
        audio.pause();
        audio.currentTime = 0;
        syncFromAudio();
        syncTransportButtons();
        updateBuffered();
        return;
      }
      lastPath = path;

      audio.pause();
      audio.src = `/api/stream-audio?path=${encodeURIComponent(path)}`;
      audio.load();
      /* No autoplay — user presses Play */

      els.buffer.style.width = "0%";
      setTimelineUi(0, 0);
      els.timeTotal.textContent = "…";
      syncTransportButtons();
    };
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", build);
  else build();
})();
