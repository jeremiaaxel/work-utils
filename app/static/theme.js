/* Theme: follow the OS, or the visitor's explicit pick.
 *
 * No-JS and first paint use the media query in app/ui.py, so there is no
 * flash either way. The toggle button (added by app/ui.py) cycles
 * light → dark and remembers the choice; clicking it again does not go
 * back to "system" — pick clear-site-data for that.
 */
(function () {
  "use strict";

  var KEY = "theme";

  function stored() {
    try { return localStorage.getItem(KEY); } catch (e) { return null; }
  }

  function apply(theme) {
    document.documentElement.setAttribute("data-theme", theme);
  }

  function toggle() {
    var root = document.documentElement;
    var next = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
    apply(next);
    try { localStorage.setItem(KEY, next); } catch (e) { /* private mode */ }
  }

  var button = document.getElementById("theme-toggle");
  if (button) { button.addEventListener("click", toggle); }

  // Another tab changed it; follow along.
  window.addEventListener("storage", function (event) {
    if (event.key === KEY && event.newValue) { apply(event.newValue); }
  });
})();
