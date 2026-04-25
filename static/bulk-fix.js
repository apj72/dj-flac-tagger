const $ = (sel) => document.querySelector(sel);
const BF_DIR_LS = "djmm.bulkFixDir";

let folderModalPath = "";
/** Current batch rows (from last successful load) */
let batchRows = [];

function esc(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function closeFolderModal() {
  const el = document.getElementById("bf-folder-modal");
  if (el) el.classList.add("hidden");
  document.removeEventListener("keydown", onFolderModalKeydown);
}

function onFolderModalKeydown(e) {
  if (e.key === "Escape") closeFolderModal();
}

async function openFolderModal() {
  let start = $("#bf-dir").value.trim();
  if (!start) {
    const resp = await fetch("/api/settings");
    const cfg = await resp.json();
    start = (cfg.destination_dir || "").trim() || "~";
  }
  document.getElementById("bf-folder-modal").classList.remove("hidden");
  document.addEventListener("keydown", onFolderModalKeydown);
  await loadFolderInModal(start);
}

async function loadFolderInModal(path) {
  const listEl = $("#bf-modal-dir-list");
  const pathEl = $("#bf-modal-path");
  const upBtn = $("#bf-modal-up");
  listEl.innerHTML = '<div class="status">Loading…</div>';
  upBtn.disabled = true;

  const resp = await fetch(`/api/browse-folders?path=${encodeURIComponent(path)}`);
  const data = await resp.json();
  if (data.error) {
    listEl.innerHTML = `<div class="status">${esc(data.error)}</div>`;
    pathEl.textContent = path;
    folderModalPath = path;
    return;
  }
  folderModalPath = data.path;
  pathEl.textContent = data.path;
  if (data.parent) {
    upBtn.disabled = false;
    upBtn.onclick = () => loadFolderInModal(data.parent);
  } else {
    upBtn.disabled = true;
    upBtn.onclick = null;
  }

  if (!data.directories || data.directories.length === 0) {
    listEl.innerHTML = '<div class="status">No subfolders (you can still use this folder)</div>';
    return;
  }
  const paths = data.directories.map((d) => d.path);
  listEl.innerHTML = data.directories
    .map(
      (d, i) =>
        `<button type="button" class="modal-dir-item" data-idx="${i}">${esc(d.name)}/</button>`
    )
    .join("");
  listEl.querySelectorAll(".modal-dir-item").forEach((btn) => {
    btn.addEventListener("click", () => {
      const i = parseInt(btn.dataset.idx, 10);
      if (!Number.isNaN(i) && paths[i]) loadFolderInModal(paths[i]);
    });
  });
}

async function resetDirToDefault() {
  const resp = await fetch("/api/settings");
  const cfg = await resp.json();
  $("#bf-dir").value = (cfg.destination_dir || "").trim();
}

function setBatchUiEnabled(hasBatch) {
  document.getElementById("bf-fetch-matches-btn").disabled = !hasBatch;
  document.getElementById("bf-apply-btn").disabled = !hasBatch;
}

function renderTable() {
  const tbody = $("#bf-tbody");
  if (!batchRows.length) {
    tbody.innerHTML = '<tr><td colspan="6" class="status">No rows. Load a batch (step 2).</td></tr>';
    setBatchUiEnabled(false);
    return;
  }
  tbody.innerHTML = batchRows
    .map((row, idx) => {
      const opts = (row.results || []).map((r, j) => {
        const label = [r.title, r.artist || r.album].filter(Boolean).join(" — ");
        const src = r.source === "discogs" ? "Discogs" : "Apple";
        const u = r.url || "";
        return `<option value="${esc(u)}">${esc(src)}: ${esc(label).slice(0, 120)}</option>`;
      });
      const selectHtml =
        opts.length > 0
          ? `<select class="bf-pick" data-idx="${idx}" style="max-width:14rem;font-size:0.85rem">
              <option value="">— pick a result —</option>
              ${opts.join("")}
            </select>`
          : '<span class="hint">—</span>';
      return `<tr data-idx="${idx}">
        <td class="th-check"><input type="checkbox" class="bf-use" data-idx="${idx}" checked /></td>
        <td class="mono" style="font-size:0.8rem;word-break:break-all">${esc(row.basename)}</td>
        <td style="font-size:0.85rem">${esc(row.query)}</td>
        <td style="font-size:0.85rem">${esc(row.title_hint || "—")}</td>
        <td>${selectHtml}</td>
        <td><input type="url" class="bf-manual" data-idx="${idx}" placeholder="https://…" style="width:100%;min-width:10rem;font-size:0.8rem" value="${esc(row.manualUrl || "")}" /></td>
      </tr>`;
    })
    .join("");

  tbody.querySelectorAll(".bf-pick").forEach((selEl) => {
    selEl.addEventListener("change", () => {
      const i = parseInt(selEl.dataset.idx, 10);
      if (Number.isNaN(i) || !batchRows[i]) return;
      batchRows[i].manualUrl = "";
      const manual = tbody.querySelector(`.bf-manual[data-idx="${i}"]`);
      if (manual) manual.value = "";
    });
  });
  setBatchUiEnabled(true);
}

async function loadBatch() {
  const dir = $("#bf-dir").value.trim();
  const rec = $("#bf-recursive").checked !== false;
  let lim = parseInt($("#bf-batch-size").value, 10);
  if (Number.isNaN(lim) || lim < 1) lim = 25;
  if (lim > 200) lim = 200;
  let off = parseInt($("#bf-offset").value, 10);
  if (Number.isNaN(off) || off < 0) off = 0;

  const st = $("#bf-range-status");
  const hint = $("#bf-load-hint");
  st.textContent = "";
  hint.textContent = "";
  if (!dir) {
    st.textContent = "Set a folder path first.";
    batchRows = [];
    renderTable();
    return;
  }

  try {
    localStorage.setItem(BF_DIR_LS, dir);
  } catch (_) {
    /* ignore */
  }

  st.textContent = "Scanning…";
  const u = new URL("/api/bulk-fix/scan", window.location.origin);
  u.searchParams.set("path", dir);
  u.searchParams.set("recursive", rec ? "1" : "0");
  u.searchParams.set("offset", String(off));
  u.searchParams.set("limit", String(lim));

  const resp = await fetch(u);
  const data = await resp.json();
  if (data.error) {
    st.textContent = data.error;
    batchRows = [];
    renderTable();
    return;
  }

  const total = data.total ?? 0;
  const items = data.items || [];
  batchRows = items.map((it) => ({
    filepath: it.filepath,
    basename: it.basename,
    query: it.query,
    title_hint: it.title_hint || "",
    results: [],
    manualUrl: "",
  }));

  const end = off + items.length;
  st.textContent = `Folder: ${data.root} — ${total} FLAC file(s) total. Showing ${items.length ? off + 1 : 0}–${end} (offset ${off}, limit ${lim}).`;
  if (end < total) {
    hint.textContent = `For the next chunk, set offset to ${end} (or increase “Files per pass”) and click Load batch again.`;
  } else if (total > 0) {
    hint.textContent = "You are at the end of the list (or the offset is past the last file).";
  } else {
    hint.textContent = "No .flac files in this folder with the current options.";
  }

  renderTable();
  $("#bf-result").classList.add("hidden");
}

async function fetchMatches() {
  if (!batchRows.length) return;
  const status = $("#bf-fetch-status");
  const btn = $("#bf-fetch-matches-btn");
  status.classList.remove("hidden");
  status.textContent = "Searching (this may take a minute for large batches)…";
  btn.disabled = true;

  const paths = batchRows.map((r) => r.filepath);
  const resp = await fetch("/api/bulk-fix/suggest", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ paths }),
  });
  const data = await resp.json();
  btn.disabled = false;
  status.classList.add("hidden");

  if (data.error) {
    status.classList.remove("hidden");
    status.textContent = data.error;
    return;
  }

  const byPath = {};
  (data.items || []).forEach((it) => {
    byPath[it.filepath] = it;
  });

  batchRows.forEach((row) => {
    const got = byPath[row.filepath];
    row.results = got && !got.error ? got.results || [] : [];
    if (got && got.error) {
      row.fetchError = got.error;
    } else {
      row.fetchError = null;
    }
  });

  renderTable();
  status.classList.remove("hidden");
  status.textContent = "Matches loaded. Review each row, then apply.";
  setTimeout(() => status.classList.add("hidden"), 5000);
}

function collectApplyPayload() {
  const tbody = $("#bf-tbody");
  const items = [];
  batchRows.forEach((row, idx) => {
    const use = tbody.querySelector(`.bf-use[data-idx="${idx}"]`);
    if (!use || !use.checked) return;
    const manual = tbody.querySelector(`.bf-manual[data-idx="${idx}"]`);
    const pick = tbody.querySelector(`.bf-pick[data-idx="${idx}"]`);
    let url = (manual && manual.value.trim()) || "";
    if (!url && pick && pick.value) url = pick.value.trim();
    if (!url) return;
    items.push({
      filepath: row.filepath,
      source_url: url,
      title_hint: row.title_hint || "",
    });
  });
  return items;
}

async function applySelected() {
  const items = collectApplyPayload();
  const out = $("#bf-result");
  if (!items.length) {
    out.className = "result error";
    out.classList.remove("hidden");
    out.innerHTML =
      '<div class="result-title">Nothing to apply</div><div class="result-detail">Check at least one row and choose a match or enter a URL.</div>';
    return;
  }
  if (!window.confirm(`Apply metadata to ${items.length} file(s) from the selected sources?`)) return;

  out.classList.add("hidden");
  const btn = $("#bf-apply-btn");
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Applying…';

  const resp = await fetch("/api/bulk-fix/apply", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      items,
      rename_to_tags: $("#bf-rename").checked === true,
      record_in_log: true,
    }),
  });
  const data = await resp.json();
  btn.disabled = false;
  btn.textContent = "Apply metadata to selected rows";
  out.classList.remove("hidden");

  if (data.error) {
    out.className = "result error";
    out.innerHTML = `<div class="result-title">Error</div><div class="result-detail">${esc(data.error)}</div>`;
    return;
  }

  const s = data.summary || {};
  const results = data.results || [];
  const errLines = results
    .filter((r) => r.status === "error")
    .slice(0, 20)
    .map((r) => `• ${esc((r.filepath || "").split("/").pop())}: ${esc(r.reason || "error")}`);

  out.className = "result";
  out.innerHTML = `<div class="result-title">Batch finished</div>
    <div class="result-detail">OK: <strong>${s.ok ?? 0}</strong> · errors: <strong>${s.errors ?? 0}</strong> · skipped: <strong>${s.skipped ?? 0}</strong></div>
    ${errLines.length ? `<p class="hint" style="margin-top:0.5rem"><strong>Issues:</strong><br/>${errLines.join("<br/>")}</p>` : ""}`;
}

document.getElementById("bf-choose-btn").addEventListener("click", openFolderModal);
document.getElementById("bf-default-btn").addEventListener("click", () => {
  resetDirToDefault();
});
document.getElementById("bf-modal-select").addEventListener("click", () => {
  if (folderModalPath) {
    $("#bf-dir").value = folderModalPath;
    closeFolderModal();
  }
});
document.getElementById("bf-modal-cancel").addEventListener("click", closeFolderModal);
document.getElementById("bf-folder-modal").addEventListener("click", (e) => {
  if (e.target && e.target.id === "bf-folder-modal") closeFolderModal();
});
document.getElementById("bf-load-batch-btn").addEventListener("click", loadBatch);
document.getElementById("bf-next-batch-btn").addEventListener("click", () => {
  let lim = parseInt($("#bf-batch-size").value, 10);
  if (Number.isNaN(lim) || lim < 1) lim = 25;
  let off = parseInt($("#bf-offset").value, 10);
  if (Number.isNaN(off) || off < 0) off = 0;
  $("#bf-offset").value = String(off + lim);
  loadBatch();
});
document.getElementById("bf-fetch-matches-btn").addEventListener("click", fetchMatches);
document.getElementById("bf-apply-btn").addEventListener("click", applySelected);

try {
  const qp = new URLSearchParams(window.location.search);
  const fromQuery = (qp.get("dir") || "").trim();
  if (fromQuery) {
    $("#bf-dir").value = fromQuery;
    try {
      localStorage.setItem(BF_DIR_LS, fromQuery);
    } catch (_) {
      /* ignore */
    }
  } else {
    const s = localStorage.getItem(BF_DIR_LS);
    if (s && s.trim()) $("#bf-dir").value = s.trim();
  }
} catch (_) {
  /* ignore */
}
