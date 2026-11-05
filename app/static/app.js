/* app.js — shared, tiny, on every page.
 *
 * Detects a newer build: the page embeds its build stamp (data-build on
 * #update-banner); this polls /build and reveals the banner when they
 * differ. A refresh then picks up the new code — and the stamp in the
 * asset URLs guarantees the refreshed page cannot reuse cached scripts.
 */
(function () {
  "use strict";

  var POLL_MS = 30000;

  function banner() { return document.getElementById("update-banner"); }

  function check() {
    var box = banner();
    if (!box) { return; }
    fetch("/build").then(function (response) { return response.text(); })
      .then(function (running) {
        if (running && running.trim() !== box.dataset.build) {
          box.classList.remove("hidden");
        }
      })
      .catch(function () { /* offline — try again on the next tick */ });
  }

  document.addEventListener("click", function (event) {
    if (event.target && event.target.id === "update-refresh") {
      window.location.reload();
    }
  });

  setInterval(check, POLL_MS);
  check();
})();
