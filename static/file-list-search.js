/* Shared file-list search: filter input + type-to-jump.
   Exposes: DJMM.initFileListSearch({ listId, onSelect, pageClass }) */
(function () {
  "use strict";

  var instances = {};
  var jumpChar = "";
  var jumpIdx = -1;
  var jumpTimer = null;

  function focusedFieldConsumesKeys(el) {
    if (!el || el.nodeType !== Node.ELEMENT_NODE) return false;
    if (el.isContentEditable) return true;
    var tag = el.tagName.toLowerCase();
    if (tag === "textarea" || tag === "select") return true;
    if (tag === "input") {
      var type = (el.type || "text").toLowerCase();
      return (
        type === "" || type === "text" || type === "search" || type === "url" ||
        type === "email" || type === "password" || type === "tel" ||
        type === "number" || type === "date" || type === "time" ||
        type === "datetime-local" || type === "month" || type === "week"
      );
    }
    return false;
  }

  function visibleItems(list) {
    return Array.prototype.slice.call(
      list.querySelectorAll(".file-item:not(.file-list-hidden)")
    );
  }

  function applyFilter(inst) {
    var q = inst.input.value.toLowerCase();
    var items = Array.prototype.slice.call(
      inst.list.querySelectorAll(".file-item")
    );
    var shown = 0;
    items.forEach(function (el) {
      var name = el.querySelector(".file-name");
      var text = name ? name.textContent.toLowerCase() : "";
      if (!q || text.indexOf(q) !== -1) {
        el.classList.remove("file-list-hidden");
        shown++;
      } else {
        el.classList.add("file-list-hidden");
      }
    });
    inst.count.textContent = q ? shown + " of " + items.length : "";
  }

  function clearFilter(inst) {
    inst.input.value = "";
    applyFilter(inst);
  }

  function buildSearchBar(list) {
    var bar = document.createElement("div");
    bar.className = "file-list-search-bar";
    var input = document.createElement("input");
    input.type = "search";
    input.placeholder = "Filter files…";
    input.className = "file-list-search-input";
    var count = document.createElement("span");
    count.className = "file-list-search-count";
    var clear = document.createElement("button");
    clear.type = "button";
    clear.className = "btn btn-secondary file-list-search-clear";
    clear.textContent = "×";
    clear.title = "Clear filter";
    bar.appendChild(input);
    bar.appendChild(count);
    bar.appendChild(clear);
    list.parentNode.insertBefore(bar, list);
    return { bar: bar, input: input, count: count, clear: clear };
  }

  function initFileListSearch(opts) {
    var listId = opts.listId;
    var onSelect = opts.onSelect;
    var pageClass = opts.pageClass || null;
    var list = document.getElementById(listId);
    if (!list) return;

    var inst = instances[listId];
    if (inst) {
      inst.onSelect = onSelect;
      clearFilter(inst);
      return;
    }

    var ui = buildSearchBar(list);
    inst = {
      list: list,
      input: ui.input,
      count: ui.count,
      bar: ui.bar,
      onSelect: onSelect,
      pageClass: pageClass,
    };
    instances[listId] = inst;

    ui.input.addEventListener("input", function () {
      applyFilter(inst);
    });
    ui.input.addEventListener("keydown", function (e) {
      if (e.key === "Escape") {
        clearFilter(inst);
        ui.input.blur();
      }
    });
    ui.clear.addEventListener("click", function () {
      clearFilter(inst);
      ui.input.blur();
    });
  }

  function handleTypeToJump(e) {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.key.length !== 1) return;
    if (focusedFieldConsumesKeys(e.target)) return;
    if (window.DJMM && DJMM.isFolderPickerOpen && DJMM.isFolderPickerOpen()) return;

    var inst = null;
    var keys = Object.keys(instances);
    for (var i = 0; i < keys.length; i++) {
      var candidate = instances[keys[i]];
      if (candidate.pageClass && !document.body.classList.contains(candidate.pageClass)) continue;
      if (candidate.list.offsetParent === null) continue;
      inst = candidate;
      break;
    }
    if (!inst) return;

    var ch = e.key.toLowerCase();
    var items = visibleItems(inst.list);
    if (!items.length) return;

    var matches = [];
    for (var j = 0; j < items.length; j++) {
      var fn = items[j].querySelector(".file-name");
      if (fn && fn.textContent.toLowerCase().charAt(0) === ch) {
        matches.push(j);
      }
    }
    if (!matches.length) return;

    e.preventDefault();

    var nextMatchIdx = 0;
    if (ch === jumpChar && jumpTimer) {
      var curSel = -1;
      for (var k = 0; k < matches.length; k++) {
        if (items[matches[k]].classList.contains("selected")) {
          curSel = k;
          break;
        }
      }
      nextMatchIdx = curSel >= 0 ? (curSel + 1) % matches.length : 0;
    }
    jumpChar = ch;
    clearTimeout(jumpTimer);
    jumpTimer = setTimeout(function () {
      jumpChar = "";
      jumpTimer = null;
    }, 800);

    var row = items[matches[nextMatchIdx]];
    if (row && inst.onSelect) {
      inst.onSelect(row);
      row.scrollIntoView({ block: "nearest", behavior: "auto" });
    }
  }

  document.addEventListener("keydown", handleTypeToJump, true);

  window.DJMM = window.DJMM || {};
  window.DJMM.initFileListSearch = initFileListSearch;
})();
