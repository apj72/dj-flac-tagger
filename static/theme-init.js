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
})();
