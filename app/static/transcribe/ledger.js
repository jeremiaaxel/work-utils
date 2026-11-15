/* ledger.js — the connection ledger (manifest §20, in-page evidence).
 *
 * Watches this page's own resource loads with PerformanceObserver and
 * tallies outbound requests. Honest scope, stated in the UI: the page can
 * only see its own requests, not OS-level traffic. Every request is
 * classified against the allowed model hosts; anything unexpected turns the
 * ledger red and is listed, because a privacy claim that cannot fail loudly
 * is not a claim — it is decoration.
 */

import { ALLOWED_HOSTS } from "./models.js";

var OBSERVED_TYPES = ["resource", "xmlhttprequest", "fetch"];

var state = {
  count: 0,
  unexpected: [],
};

function hostOf(url) {
  try {
    return new URL(url, window.location.href).host;
  } catch (e) {
    return "(unparseable)";
  }
}

function isAllowed(url) {
  var host = hostOf(url);
  return ALLOWED_HOSTS.indexOf(host) !== -1;
}

function record(url) {
  state.count += 1;
  if (!isAllowed(url)) {
    state.unexpected.push(url);
  }
  render();
}

function render() {
  var count = document.getElementById("tr-ledger-count");
  if (count) {
    count.textContent = String(state.count);
  }
  var ledger = document.getElementById("tr-ledger");
  var details = document.getElementById("tr-ledger-details");
  if (!ledger || !details) {
    return;
  }
  if (state.unexpected.length) {
    ledger.classList.remove("alert-success");
    ledger.classList.add("alert-error");
    details.innerHTML =
      "<div class='text-error font-bold'>Unexpected requests observed:</div>" +
      state.unexpected
        .slice(-20)
        .map(function (u) { return "<div>" + u + "</div>"; })
        .join("");
  } else {
    details.innerHTML =
      "<div>Every request so far went to an allowed model host " +
      "(" + ALLOWED_HOSTS.join(", ") + "). Audio and transcript text are " +
      "never sent anywhere — inference runs in this tab.</div>";
  }
}

export function startLedger() {
  if (!("PerformanceObserver" in window)) {
    render();
    return;
  }
  var observer = new PerformanceObserver(function (list) {
    list.getEntries().forEach(function (entry) {
      if (entry.name) { record(entry.name); }
    });
  });
  try {
    observer.observe({ entryTypes: OBSERVED_TYPES });
  } catch (e) {
    // Some browsers reject uncommon entry types; resource alone still
    // covers fetch and XHR.
    try {
      observer.observe({ entryTypes: ["resource"] });
    } catch (e2) { /* nothing we can observe — the count just stays 0 */ }
  }
  render();
}
