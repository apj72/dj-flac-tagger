/* Playlist Builder — browse the Music library, select tracks, create a playlist */
(function () {
  "use strict";

  const RENDER_CAP = 1000; // max rows drawn at once; selection still works on all filtered

  const nameInput = document.getElementById("pb-name");
  const createBtn = document.getElementById("pb-create-btn");
  const selectedCount = document.getElementById("pb-selected-count");
  const createStatus = document.getElementById("pb-create-status");
  const searchInput = document.getElementById("pb-search");
  const selectAllBtn = document.getElementById("pb-select-all");
  const clearBtn = document.getElementById("pb-clear");
  const reloadBtn = document.getElementById("pb-reload");
  const status = document.getElementById("pb-status");
  const tableWrap = document.getElementById("pb-table-wrap");
  const tbody = document.getElementById("pb-body");
  const checkAll = document.getElementById("pb-check-all");

  let allTracks = [];
  let filtered = [];
  const selected = new Set(); // persistent_ids

  function esc(s) {
    const d = document.createElement("div");
    d.textContent = s == null ? "" : s;
    return d.innerHTML;
  }

  function fmtDuration(secs) {
    if (!secs || secs <= 0) return "--";
    const m = Math.floor(secs / 60);
    const s = Math.floor(secs % 60);
    return `${m}:${s.toString().padStart(2, "0")}`;
  }

  function updateCreateState() {
    const n = selected.size;
    selectedCount.textContent = `${n} selected`;
    createBtn.disabled = nameInput.value.trim() === "";
  }

  function applyFilter() {
    const q = searchInput.value.trim().toLowerCase();
    if (!q) {
      filtered = allTracks;
    } else {
      filtered = allTracks.filter((t) =>
        (t.title || "").toLowerCase().includes(q) ||
        (t.artist || "").toLowerCase().includes(q) ||
        (t.album || "").toLowerCase().includes(q)
      );
    }
    renderTable();
  }

  function renderTable() {
    const shown = filtered.slice(0, RENDER_CAP);
    tbody.innerHTML = shown
      .map(
        (t) => `<tr class="pb-row" data-pid="${esc(t.persistent_id)}">
        <td class="pb-td-check"><input type="checkbox" class="pb-check" data-pid="${esc(t.persistent_id)}" ${selected.has(t.persistent_id) ? "checked" : ""} aria-label="Select ${esc(t.title)}" /></td>
        <td class="pb-td-title">${esc(t.title)}</td>
        <td class="pb-td-artist">${esc(t.artist)}</td>
        <td class="pb-td-album">${esc(t.album)}</td>
        <td class="pb-td-dur">${fmtDuration(t.duration)}</td>
      </tr>`
      )
      .join("");

    let msg = `${filtered.length} track${filtered.length !== 1 ? "s" : ""}`;
    if (allTracks.length && filtered.length !== allTracks.length) {
      msg += ` of ${allTracks.length}`;
    }
    if (filtered.length > RENDER_CAP) {
      msg += ` — showing first ${RENDER_CAP}, refine your search to see more`;
    }
    status.textContent = msg;

    syncCheckAll();
  }

  function syncCheckAll() {
    const shown = filtered.slice(0, RENDER_CAP);
    const allShownSelected = shown.length > 0 && shown.every((t) => selected.has(t.persistent_id));
    checkAll.checked = allShownSelected;
    checkAll.indeterminate = !allShownSelected && shown.some((t) => selected.has(t.persistent_id));
  }

  async function loadLibrary() {
    status.classList.remove("hidden");
    status.innerHTML = '<span class="spinner"></span> Loading your library…';
    tableWrap.classList.add("hidden");
    reloadBtn.disabled = true;
    try {
      const resp = await fetch("/api/music-library/tracks");
      const data = await resp.json();
      if (!resp.ok || data.error) {
        status.innerHTML = `<span class="error">${esc(data.error || "Failed to load library")}</span>`;
        return;
      }
      allTracks = data.tracks || [];
      tableWrap.classList.remove("hidden");
      applyFilter();
    } catch (e) {
      status.innerHTML = `<span class="error">Failed to load library: ${esc(e.message)}</span>`;
    } finally {
      reloadBtn.disabled = false;
    }
  }

  async function createPlaylist() {
    const name = nameInput.value.trim();
    if (!name) return;
    createBtn.disabled = true;
    const originalLabel = createBtn.textContent;
    createBtn.textContent = "Creating…";
    createStatus.classList.remove("hidden");
    createStatus.innerHTML = '<span class="spinner"></span> Creating playlist in Music…';
    try {
      const resp = await fetch("/api/music-library/create-playlist", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, track_ids: Array.from(selected) }),
      });
      const data = await resp.json();
      if (!resp.ok || data.error) {
        createStatus.innerHTML = `<span class="error">${esc(data.error || "Failed to create playlist")}</span>`;
        return;
      }
      let msg = `Created “${esc(data.name)}” with ${data.added} track${data.added !== 1 ? "s" : ""}.`;
      if (data.added < data.requested) {
        msg += ` (${data.requested - data.added} could not be added.)`;
      }
      createStatus.innerHTML = `<span class="pb-success">${msg}</span>`;
      selected.clear();
      nameInput.value = "";
      renderTable();
      updateCreateState();
    } catch (e) {
      createStatus.innerHTML = `<span class="error">Failed to create playlist: ${esc(e.message)}</span>`;
    } finally {
      createBtn.textContent = originalLabel;
      updateCreateState();
    }
  }

  // --- Events ---

  tbody.addEventListener("change", (e) => {
    const cb = e.target.closest(".pb-check");
    if (!cb) return;
    const pid = cb.dataset.pid;
    if (cb.checked) selected.add(pid);
    else selected.delete(pid);
    updateCreateState();
    syncCheckAll();
  });

  checkAll.addEventListener("change", () => {
    const shown = filtered.slice(0, RENDER_CAP);
    if (checkAll.checked) shown.forEach((t) => selected.add(t.persistent_id));
    else shown.forEach((t) => selected.delete(t.persistent_id));
    renderTable();
    updateCreateState();
  });

  selectAllBtn.addEventListener("click", () => {
    filtered.forEach((t) => selected.add(t.persistent_id));
    renderTable();
    updateCreateState();
  });

  clearBtn.addEventListener("click", () => {
    selected.clear();
    renderTable();
    updateCreateState();
  });

  reloadBtn.addEventListener("click", loadLibrary);
  createBtn.addEventListener("click", createPlaylist);
  nameInput.addEventListener("input", updateCreateState);

  let searchTimer = null;
  searchInput.addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(applyFilter, 150);
  });

  loadLibrary();
})();
