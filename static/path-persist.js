/**
 * Last browsed audio folder shared by Fix Metadata and Inspect (localStorage).
 */
const DJMM_LAST_AUDIO_BROWSE_DIR = "djmm.lastAudioBrowseDir";

function djmmGetLastAudioBrowseDir() {
  try {
    return localStorage.getItem(DJMM_LAST_AUDIO_BROWSE_DIR) || "";
  } catch (_) {
    return "";
  }
}

function djmmSetLastAudioBrowseDir(dir) {
  const d = String(dir || "").trim();
  if (!d) return;
  try {
    localStorage.setItem(DJMM_LAST_AUDIO_BROWSE_DIR, d);
  } catch (_) {
    /* ignore quota / private mode */
  }
}

// ---- Per-page UI draft (localStorage; survives full navigations between tabs) ----
const DJMM_PAGE_STORE = "djmm.pageState";

function djmmPageStateGetAll() {
  try {
    const raw = localStorage.getItem(DJMM_PAGE_STORE);
    if (!raw) return { v: 1, pages: {} };
    const o = JSON.parse(raw);
    if (!o || o.v !== 1 || typeof o.pages !== "object" || o.pages === null) return { v: 1, pages: {} };
    return o;
  } catch (_) {
    return { v: 1, pages: {} };
  }
}

function djmmPageStateSetPage(pageKey, data) {
  try {
    const store = djmmPageStateGetAll();
    if (data == null) delete store.pages[pageKey];
    else store.pages[pageKey] = data;
    localStorage.setItem(DJMM_PAGE_STORE, JSON.stringify(store));
  } catch (_) {
    /* quota */
  }
}

function djmmPageStateGetPage(pageKey) {
  const p = djmmPageStateGetAll().pages[pageKey];
  return p !== undefined ? p : null;
}

const djmmPageStateTimers = {};
function djmmPageStateSchedule(pageKey, getDataFn, ms = 400) {
  if (djmmPageStateTimers[pageKey]) clearTimeout(djmmPageStateTimers[pageKey]);
  djmmPageStateTimers[pageKey] = setTimeout(() => {
    djmmPageStateTimers[pageKey] = null;
    try {
      djmmPageStateSetPage(pageKey, getDataFn());
    } catch (_) {
      /* ignore */
    }
  }, ms);
}
