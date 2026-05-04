/* Apply saved appearance before first paint. Load in <head> on every page. */
(function () {
  var KEY = "djmm.themePreference";

  function resolve(pref) {
    if (pref === "light") return "light";
    if (pref === "dark") return "dark";
    if (window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches) {
      return "light";
    }
    return "dark";
  }

  var pref = localStorage.getItem(KEY);
  if (pref !== "light" && pref !== "dark" && pref !== "system") pref = "system";

  var effective = pref === "light" || pref === "dark" ? pref : resolve("system");
  document.documentElement.dataset.theme = effective;

  window.djmmApplyThemePreference = function (p) {
    if (p !== "light" && p !== "dark" && p !== "system") p = "system";
    localStorage.setItem(KEY, p);
    var eff = p === "light" || p === "dark" ? p : resolve("system");
    document.documentElement.dataset.theme = eff;
  };
  window.djmmGetThemePreference = function () {
    var x = localStorage.getItem(KEY);
    if (x === "light" || x === "dark" || x === "system") return x;
    return "system";
  };
  window.djmmResolveThemeFromPreference = resolve;

  window.matchMedia("(prefers-color-scheme: light)").addEventListener("change", function () {
    if (localStorage.getItem(KEY) === "system") {
      document.documentElement.dataset.theme = resolve("system");
    }
  });

  /* Page background image (scenic hero): on by default; off = solid --bg only */
  var BG_KEY = "djmm.pageBackgroundEnabled";

  function applyPageBackgroundFromStorage() {
    var raw = localStorage.getItem(BG_KEY);
    var off = raw === "0" || raw === "false";
    document.documentElement.setAttribute("data-page-background", off ? "off" : "on");
  }

  applyPageBackgroundFromStorage();

  window.djmmApplyPageBackgroundEnabled = function (enabled) {
    localStorage.setItem(BG_KEY, enabled ? "1" : "0");
    document.documentElement.setAttribute("data-page-background", enabled ? "on" : "off");
  };

  window.djmmGetPageBackgroundEnabled = function () {
    var raw = localStorage.getItem(BG_KEY);
    if (raw === "0" || raw === "false") return false;
    return true;
  };
})();
