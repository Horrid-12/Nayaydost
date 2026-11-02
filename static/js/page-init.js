(function () {
  var path = window.location.pathname.replace(/\/+$/, "") || "/";
  var hash = window.location.hash.toLowerCase();
  var page =
    path === "/guide" || hash === "#guide"
      ? "guide"
      : path === "/legal-aid" || hash === "#legal-aid"
        ? "legal-aid"
        : "workspace";
  document.documentElement.setAttribute("data-page", page);
})();
