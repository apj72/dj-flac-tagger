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
