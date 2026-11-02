/*
 * Apply the saved theme before the first paint so the page never flashes a
 * bright parchment background in a dark room (or the reverse).
 */
(function () {
  "use strict";

  var STORAGE_KEY = "nyayadost.theme";
  var stored = null;
  try {
    stored = window.localStorage.getItem(STORAGE_KEY);
  } catch (error) {
    stored = null;
  }

  var prefersDark = false;
  try {
    prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  } catch (error) {
    prefersDark = false;
  }

  var theme = stored === "dark" || stored === "light" ? stored : prefersDark ? "dark" : "light";
  document.documentElement.setAttribute("data-theme", theme);
})();
