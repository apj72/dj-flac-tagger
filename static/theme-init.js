/* Apply saved appearance before first paint. Load in <head> on every page. */
(function () {
  var KEY = "djmm.themePreference";
  var BG_KEY = "djmm.pageBackgroundEnabled";

  function resolve(pref) {
    if (pref === "light") return "light";
    if (pref === "dark") return "dark";
    if (window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches) {
      return "light";
    }
    return "dark";
  }

  function applyTheme(pref) {
    var eff = pref === "light" || pref === "dark" ? pref : resolve("system");
    document.documentElement.dataset.theme = eff;
  }

  function saveToServer(key, value) {
    var body = {};
    body[key] = value;
    try {
      fetch("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }).catch(function () {});
    } catch (_) {}
  }

  var pref = localStorage.getItem(KEY);
  if (pref !== "light" && pref !== "dark" && pref !== "system") pref = "system";
  applyTheme(pref);

  window.djmmApplyThemePreference = function (p) {
    if (p !== "light" && p !== "dark" && p !== "system") p = "system";
    localStorage.setItem(KEY, p);
    applyTheme(p);
    saveToServer("theme_preference", p);
  };
  window.djmmGetThemePreference = function () {
    var x = localStorage.getItem(KEY);
    if (x === "light" || x === "dark" || x === "system") return x;
    return "system";
  };
  window.djmmResolveThemeFromPreference = resolve;

  window.matchMedia("(prefers-color-scheme: light)").addEventListener("change", function () {
    if (localStorage.getItem(KEY) === "system") {
      applyTheme("system");
    }
  });

  /* Page background image (scenic hero): on by default; off = solid --bg only */
  function applyBg(enabled) {
    document.documentElement.setAttribute("data-page-background", enabled ? "on" : "off");
  }

  var bgRaw = localStorage.getItem(BG_KEY);
  applyBg(bgRaw !== "0" && bgRaw !== "false");

  window.djmmApplyPageBackgroundEnabled = function (enabled) {
    localStorage.setItem(BG_KEY, enabled ? "1" : "0");
    applyBg(enabled);
    saveToServer("page_background_enabled", !!enabled);
  };

  window.djmmGetPageBackgroundEnabled = function () {
    var raw = localStorage.getItem(BG_KEY);
    if (raw === "0" || raw === "false") return false;
    return true;
  };

  /* On fresh load (empty localStorage), restore from server config */
  var needsRestore = !localStorage.getItem(KEY) && !localStorage.getItem(BG_KEY);
  if (needsRestore) {
    fetch("/api/settings")
      .then(function (r) { return r.json(); })
      .then(function (cfg) {
        var tp = cfg.theme_preference;
        if (tp === "light" || tp === "dark" || tp === "system") {
          localStorage.setItem(KEY, tp);
          applyTheme(tp);
        }
        if (cfg.page_background_enabled === false) {
          localStorage.setItem(BG_KEY, "0");
          applyBg(false);
        } else if (cfg.page_background_enabled === true) {
          localStorage.setItem(BG_KEY, "1");
        }
      })
      .catch(function () {});
  }
})();
