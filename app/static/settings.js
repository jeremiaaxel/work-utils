/* settings — load, edit and save the runtime provider settings.
 *
 * Server-rendered page; this file only fetches. Secrets are write-only:
 * the GET response never contains them, so a blank field means "keep".
 */
(function () {
  "use strict";

  var API = "/api/settings";
  var PW_KEY = "app-password";

  function $(id) { return document.getElementById(id); }
  function val(id) { var el = $(id); return el ? el.value.trim() : ""; }

  function password() {
    var field = $("set-password");
    if (field && field.value) { return field.value; }
    try { return (localStorage.getItem(PW_KEY) || "").trim(); }
    catch (e) { return ""; }
  }

  function toast(message, kind) {
    var box = $("set-toast");
    if (!box) { return; }
    var item = document.createElement("div");
    item.className = "alert alert-" + (kind || "info") + " shadow-lg";
    item.textContent = message;
    box.appendChild(item);
    setTimeout(function () { item.remove(); }, 4000);
  }

  function status(message) {
    var el = $("set-status");
    if (el) { el.textContent = message; }
  }

  function fill(data) {
    $("set-translation_primary").value = data.translation_primary || "";
    $("set-translation_fallback").value = data.translation_fallback || "";
    $("set-ocr_engine").value = data.ocr_engine || "paddle";

    var state = $("set-deepl_api_key-state");
    if (state) {
      state.textContent = data.deepl_api_key_set ? "saved" : "not set";
      state.classList.remove("hidden");
    }
    if (data.lingva_url) { $("set-lingva_url").value = data.lingva_url; }

    var hint = $("set-ocr-hint");
    if (hint) {
      var suffix = data.ocr_engines && data.ocr_engines.indexOf("tesseract") >= 0
        ? (data.tesseract_available
          ? " Tesseract is installed on this server."
          : " Tesseract is not installed on this server yet.")
        : "";
      hint.textContent =
        "Tesseract keeps pages on this server — use it for confidential files." +
        suffix;
    }
  }

  function load() {
    fetch(API)
      .then(function (r) { return r.json(); })
      .then(fill)
      .catch(function () { status("Could not load the current settings."); });
  }

  function save() {
    var body = {
      translation_primary: val("set-translation_primary"),
      translation_fallback: val("set-translation_fallback"),
      ocr_engine: val("set-ocr_engine"),
      deepl_api_key: val("set-deepl_api_key") || null,
      lingva_url: val("set-lingva_url") || null,
    };
    // null means "leave unchanged" — a deliberate clear needs whitespace-only
    // sent as "", handled below by sending "" for touched empty fields.
    ["deepl_api_key", "lingva_url"].forEach(function (f) {
      var el = $(f === "deepl_api_key" ? "set-deepl_api_key" : "set-lingva_url");
      if (el && el.dataset.touched && !el.value.trim()) { body[f] = ""; }
    });

    fetch(API, {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
        "X-App-Password": password(),
      },
      body: JSON.stringify(body),
    })
      .then(function (r) {
        if (r.status === 401 || r.status === 503) {
          throw new Error("wrong or missing app password");
        }
        if (!r.ok) { throw new Error("HTTP " + r.status); }
        return r.json();
      })
      .then(function (data) {
        fill(data);
        ["set-deepl_api_key", "set-lingva_url"].forEach(function (id) {
          var el = $(id);
          if (el) { el.value = ""; delete el.dataset.touched; }
        });
        try { localStorage.setItem(PW_KEY, password()); } catch (e) { /* */ }
        status("Saved.");
        toast("Settings saved", "success");
      })
      .catch(function (e) {
        status("");
        toast(e.message || "Saving failed", "error");
      });
  }

  ["set-deepl_api_key", "set-lingva_url"].forEach(function (id) {
    var el = $(id);
    if (el) {
      el.addEventListener("input", function () { el.dataset.touched = "1"; });
    }
  });

  var button = $("set-save");
  if (button) { button.addEventListener("click", save); }

  load();
})();
