/* Shared folder-picker modal – one instance, any page.
   Exposes: DJMM.openFolderPicker({ startPath, onSelect, onCancel })
            DJMM.isFolderPickerOpen()                                 */
(function () {
  "use strict";

  var MODAL_ID = "djmm-folder-picker-modal";
  var overlay, pathEl, upBtn, dirList, selectBtn, cancelBtn;
  var currentPath = "";
  var onSelect = null;
  var onCancel = null;

  function escHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function build() {
    overlay = document.createElement("div");
    overlay.id = MODAL_ID;
    overlay.className = "modal-overlay hidden";
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "true");
    overlay.innerHTML =
      '<div class="modal-card">' +
        "<h3>Choose folder</h3>" +
        '<div class="modal-path mono" data-fp="path"></div>' +
        '<div class="modal-nav">' +
          '<button type="button" class="btn btn-secondary" data-fp="up" disabled>' +
            "↑ Enclosing folder" +
          "</button>" +
        "</div>" +
        '<div class="modal-dir-list" data-fp="list"></div>' +
        '<div class="modal-actions">' +
          '<button type="button" class="btn btn-primary" data-fp="select">Use this folder</button>' +
          '<button type="button" class="btn btn-secondary" data-fp="cancel">Cancel</button>' +
        "</div>" +
      "</div>";

    pathEl = overlay.querySelector('[data-fp="path"]');
    upBtn = overlay.querySelector('[data-fp="up"]');
    dirList = overlay.querySelector('[data-fp="list"]');
    selectBtn = overlay.querySelector('[data-fp="select"]');
    cancelBtn = overlay.querySelector('[data-fp="cancel"]');

    selectBtn.addEventListener("click", doSelect);
    cancelBtn.addEventListener("click", doClose);
    overlay.addEventListener("click", function (e) {
      if (e.target === overlay) doClose();
    });

    document.body.appendChild(overlay);
  }

  function onKeydown(e) {
    if (e.key === "Escape") doClose();
  }

  function doClose() {
    overlay.classList.add("hidden");
    document.removeEventListener("keydown", onKeydown);
    if (typeof onCancel === "function") onCancel();
    onSelect = null;
    onCancel = null;
  }

  function doSelect() {
    if (!currentPath) return;
    var cb = onSelect;
    overlay.classList.add("hidden");
    document.removeEventListener("keydown", onKeydown);
    onSelect = null;
    onCancel = null;
    if (typeof cb === "function") cb(currentPath);
  }

  function loadFolder(path) {
    dirList.innerHTML = '<div class="status">Loading…</div>';
    upBtn.disabled = true;

    fetch("/api/browse-folders?path=" + encodeURIComponent(path))
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.error) {
          dirList.innerHTML = '<div class="status">' + escHtml(data.error) + "</div>";
          pathEl.textContent = path;
          currentPath = path;
          return;
        }
        currentPath = data.path;
        pathEl.textContent = data.path;

        if (data.parent) {
          upBtn.disabled = false;
          upBtn.onclick = function () { loadFolder(data.parent); };
        } else {
          upBtn.disabled = true;
          upBtn.onclick = null;
        }

        if (!data.directories || data.directories.length === 0) {
          dirList.innerHTML = '<div class="status">No subfolders (you can still use this folder)</div>';
          return;
        }

        var paths = data.directories.map(function (d) { return d.path; });
        dirList.innerHTML = data.directories
          .map(function (d, i) {
            return '<button type="button" class="modal-dir-item" data-idx="' + i + '">' + escHtml(d.name) + "/</button>";
          })
          .join("");

        dirList.querySelectorAll(".modal-dir-item").forEach(function (btn) {
          btn.addEventListener("click", function () {
            var i = parseInt(btn.dataset.idx, 10);
            if (!isNaN(i) && paths[i]) loadFolder(paths[i]);
          });
        });
      })
      .catch(function () {
        dirList.innerHTML = '<div class="status">Failed to load folder</div>';
        pathEl.textContent = path;
        currentPath = path;
      });
  }

  function openFolderPicker(opts) {
    if (!overlay) build();
    onSelect = opts.onSelect || null;
    onCancel = opts.onCancel || null;
    overlay.classList.remove("hidden");
    document.addEventListener("keydown", onKeydown);
    loadFolder(opts.startPath || "~");
  }

  function isFolderPickerOpen() {
    return overlay ? !overlay.classList.contains("hidden") : false;
  }

  window.DJMM = window.DJMM || {};
  window.DJMM.openFolderPicker = openFolderPicker;
  window.DJMM.isFolderPickerOpen = isFolderPickerOpen;
})();
