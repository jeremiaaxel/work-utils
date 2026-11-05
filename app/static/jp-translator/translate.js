/* jp-translator — the two-way translation page.
 *
 * The page is rendered on the server (see views.py). This file only does
 * what JavaScript has to do: the debounced auto-translate, the per-side
 * audio controls, and the furigana toggle. One speech controller is shared
 * by all four speaker buttons — only one utterance plays at a time.
 */
(function () {
  "use strict";

  var API = "/api/jp-translator";
  var PW_KEY = "app-password";
  var RATES = [0.8, 1.0, 1.2];
  var RATE_LABELS = ["0.8×", "1×", "1.2×"];

  // How long to wait after the last keystroke before auto-translating.
  var DEBOUNCE_MS = 700;

  var panels = {};

  // ── URL state (shareable, Google-translate style) ──────────────

  // Each panel owns one query parameter: understand -> ja, express -> en.
  // replaceState keeps typing from flooding the history.
  var URL_PARAMS = { "jp-understand": "ja", "jp-express": "en" };

  function saveToUrl(panel) {
    try {
      var params = new URLSearchParams(window.location.search);
      var key = URL_PARAMS[panel.id];
      var value = panel.input.value.trim();
      if (value) { params.set(key, value); }
      else { params.delete(key); }
      var query = params.toString();
      window.history.replaceState(
        null, "", window.location.pathname + (query ? "?" + query : "")
      );
    } catch (e) { /* sandboxed or no history API — text still works */ }
  }

  function restoreFromUrl(panel) {
    try {
      var params = new URLSearchParams(window.location.search);
      var value = params.get(URL_PARAMS[panel.id]);
      if (value) {
        panel.input.value = value;
        return true;
      }
    } catch (e) { /* no URLSearchParams — skip */ }
    return false;
  }

  // ── helpers ────────────────────────────────────────────────────

  function $(id) { return document.getElementById(id); }

  function password() {
    var field = $("jp-password");
    return field ? field.value : "";
  }

  function rememberPassword() {
    try { localStorage.setItem(PW_KEY, password()); } catch (e) { /* private mode */ }
  }

  function restorePassword() {
    var field = $("jp-password");
    if (!field || field.value) { return; }
    try {
      var saved = localStorage.getItem(PW_KEY);
      if (saved) { field.value = saved; }
    } catch (e) { /* private mode */ }
  }

  function toast(message, kind) {
    var box = $("jp-toast");
    if (!box) { return; }
    var item = document.createElement("div");
    item.className = "alert alert-" + (kind || "info") + " shadow-lg";
    item.textContent = message;
    box.appendChild(item);
    setTimeout(function () { item.remove(); }, 4000);
  }

  // ── text sources ───────────────────────────────────────────────

  // The text of a rendered box without its furigana: <rt>/<rp> readings are
  // dropped so copy and speech never double up the annotations.
  function canonicalText(box) {
    if (!box || box.classList.contains("hidden")) { return ""; }
    var clone = box.cloneNode(true);
    clone.querySelectorAll("rt, rp").forEach(function (el) { el.remove(); });
    return (clone.textContent || "").trim();
  }

  // The Japanese of the panel: the annotated view when it has one, else the
  // source it annotates (understand's input, express's plain translation).
  function japaneseText(panel) {
    var annotated = canonicalText(panel.furigana);
    if (annotated) { return annotated; }
    if (panel.direction === "ja_en") {
      return panel.input.value.trim();
    }
    return panel.result.textContent === panel.placeholder
      ? ""
      : panel.result.textContent.trim();
  }

  // ── selection ──────────────────────────────────────────────────

  // The user's highlighted text inside one box, or null. The selection is
  // rebuilt without <rt>/<rp> so readings stay out of speech and copies.
  function selectionIn(box) {
    var selection = window.getSelection();
    if (!selection || selection.rangeCount === 0 || selection.isCollapsed) {
      return null;
    }
    var range = selection.getRangeAt(0);
    if (!box.contains(range.commonAncestorContainer)) { return null; }
    var holder = document.createElement("div");
    holder.appendChild(range.cloneContents());
    holder.querySelectorAll("rt, rp").forEach(function (el) { el.remove(); });
    var text = (holder.textContent || "").trim();
    return text || null;
  }

  // What the speaker for one side should read. Clicking a button collapses
  // the DOM selection, so the panel remembers the last selection (side +
  // text, from selectionchange) and the speaker prefers it while the text
  // it came from is unchanged; otherwise it reads the whole side. A
  // textarea selection is live at click time and read from its value.
  function speakableText(panel, side) {
    if (side === "input") {
      if (panel.input.selectionStart !== panel.input.selectionEnd) {
        var slice = panel.input.value.slice(
          panel.input.selectionStart, panel.input.selectionEnd
        ).trim();
        if (slice) { return slice; }
      }
      return panel.input.value.trim();
    }
    if (panel.selection && panel.selection.box === panel.result) {
      return panel.selection.text;
    }
    return canonicalText(panel.result) || panel.result.textContent.trim();
  }

  // ── speech ─────────────────────────────────────────────────────

  // One controller for the whole page: every speaker button routes through
  // it, so starting one utterance cancels the other.
  var speech = {
    supported: false,
    voices: [],      // every available voice, Japanese first if found
    ready: false,
    rateIndex: 1,
    activeButton: null, // the speak button whose utterance is playing

    init: function () {
      if (!("speechSynthesis" in window) || !("SpeechSynthesisUtterance" in window)) {
        return;
      }
      this.supported = true;
      var self = this;
      function loadVoices() {
        var voices = window.speechSynthesis.getVoices();
        self.voices = voices.slice();
        self.ready = self.voices.length > 0;
      }
      loadVoices();
      window.speechSynthesis.addEventListener("voiceschanged", loadVoices);
      // Some engines never fire voiceschanged; re-check once shortly after.
      setTimeout(function () { if (!self.ready) { loadVoices(); } }, 1000);
    },

    // The best voice for the text: a Japanese one when the text is
    // Japanese, else the browser's default voice.
    pickVoice: function (japanese) {
      for (var i = 0; i < this.voices.length; i++) {
        var lang = (this.voices[i].lang || "").toLowerCase();
        if (japanese && (lang === "ja" || lang.indexOf("ja-") === 0)) {
          return this.voices[i];
        }
        if (!japanese && (lang === "en" || lang.indexOf("en-") === 0)) {
          return this.voices[i];
        }
      }
      return null;
    },

    speak: function (buttonId, text, japanese) {
      if (!text) {
        toast("Nothing to read yet", "info");
        return;
      }
      if (!this.supported) {
        toast("Speech is not supported in this browser", "warning");
        return;
      }
      var voice = this.pickVoice(japanese);
      if (!voice && japanese) {
        toast("No Japanese voice is available in this browser", "warning");
        return;
      }
      window.speechSynthesis.cancel();
      var utterance = new SpeechSynthesisUtterance(text);
      utterance.lang = japanese ? "ja-JP" : "en-US";
      if (voice) { utterance.voice = voice; }
      utterance.rate = RATES[this.rateIndex];
      var self = this;
      // Natural end and engine errors both land here; only the button that
      // is actually playing is reset.
      function done(id) {
        if (self.activeButton === id) {
          self.activeButton = null;
        }
      }
      utterance.onend = function () { done(buttonId); };
      utterance.onerror = function () { done(buttonId); };
      this.activeButton = buttonId;
      window.speechSynthesis.speak(utterance);
    },

    stop: function () {
      if (this.supported) { window.speechSynthesis.cancel(); }
      this.activeButton = null;
    },

    cycleRate: function () {
      this.rateIndex = (this.rateIndex + 1) % RATES.length;
      return RATE_LABELS[this.rateIndex];
    },
  };

  // ── rendering ──────────────────────────────────────────────────

  function showError(panel, message) {
    panel.error.textContent = message;
    panel.error.classList.remove("hidden");
    panel.error.classList.add("alert", "alert-error");
  }

  function clearError(panel) {
    panel.error.textContent = "";
    panel.error.classList.add("hidden");
    panel.error.classList.remove("alert", "alert-error");
  }

  function setBusy(panel, busy) {
    panel.loading.classList.toggle("hidden", !busy);
    // The output area itself shows the three-dot "working" animation.
    panel.result.classList.toggle("jp-busy", busy);
  }

  // The placeholder shows through opacity; real translations render full
  // strength. The pristine placeholder text is captured once at load, so
  // clearing restores it no matter what display() wrote since.
  function markResultReal(panel) {
    panel.result.classList.remove("opacity-60");
  }

  function resetResult(panel) {
    panel.result.textContent = panel.placeholder;
    panel.result.classList.add("opacity-60");
    if (panel.furigana) { panel.furigana.innerHTML = ""; }
    if (panel.furiganaBlock) { panel.furiganaBlock.classList.add("hidden"); }
  }

  function display(panel, data) {
    clearError(panel);
    panel.selection = null;
    if (panel.direction === "en_ja") {
      // The translation IS the Japanese: render it with ruby furigana on
      // the kanji, one block — like printed text.
      panel.result.innerHTML = data.ruby_html || "";
      if (!panel.result.textContent && data.translation) {
        panel.result.textContent = data.translation; // kana-only fallback
      }
    } else {
      panel.result.textContent = data.translation || "";
      if (panel.furigana) {
        if (data.ruby_html) {
          panel.furigana.innerHTML = data.ruby_html;
          if (panel.furiganaBlock) {
            panel.furiganaBlock.classList.remove("hidden");
          }
        } else {
          panel.furigana.innerHTML = "";
          if (panel.furiganaBlock) {
            panel.furiganaBlock.classList.add("hidden");
          }
        }
      }
    }
    markResultReal(panel);
  }

  // ── translation ────────────────────────────────────────────────

  function translate(panel) {
    var text = panel.input.value.trim();

    // An empty input empties the panel instead of asking the provider.
    if (!text) {
      panel.requestId += 1; // invalidate anything in flight
      panel.submitted = "";
      clearError(panel);
      resetResult(panel);
      setBusy(panel, false);
      saveToUrl(panel);
      return;
    }
    if (!password()) {
      toast("Enter the password first", "warning");
      return;
    }
    rememberPassword();
    clearError(panel);
    setBusy(panel, true);
    panel.requestId += 1;
    var requestId = panel.requestId;

    fetch(API + "/translate", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-App-Password": password(),
      },
      body: JSON.stringify({ text: text, direction: panel.direction }),
    }).then(function (response) {
      if (requestId !== panel.requestId) { return null; } // superseded
      if (response.status === 401) { throw new Error("Wrong password"); }
      if (response.status === 503) {
        throw new Error("No password is configured on the server");
      }
      if (response.status === 409) {
        throw new Error("Already translating that text");
      }
      if (response.status === 413) {
        throw new Error("That text is too long to translate");
      }
      if (!response.ok) {
        throw new Error("Translation failed (" + response.status + ")");
      }
      return response.json();
    }).then(function (data) {
      if (!data || requestId !== panel.requestId) { return; }
      panel.submitted = text;
      display(panel, data);
      saveToUrl(panel);
    }).catch(function (err) {
      if (requestId !== panel.requestId) { return; }
      showError(panel, err.message || "Translation failed");
    }).finally(function () {
      if (requestId === panel.requestId) { setBusy(panel, false); }
    });
  }

  // Auto-translate: restart the timer on every keystroke, translate when
  // it fires. Always on — typing is the only input the page needs.
  function scheduleTranslate(panel) {
    if (panel.timer) { clearTimeout(panel.timer); }
    panel.timer = setTimeout(function () {
      panel.timer = null;
      translate(panel);
    }, DEBOUNCE_MS);
  }

  // ── actions ────────────────────────────────────────────────────

  // Plain text of a box; for a rendered box, readings are dropped.
  function plainText(panel, box) {
    return box === panel.input
      ? panel.input.value.trim()
      : canonicalText(box) || box.textContent.trim();
  }

  // Text with readings inline: kanji(furigana), e.g. 日本語(にほんご).
  // Built by walking the rendered ruby so it always matches what is shown.
  function furiganaText(panel, box) {
    if (box === panel.input) { return panel.input.value.trim(); }
    var clone = box.cloneNode(true);
    clone.querySelectorAll("rp").forEach(function (el) { el.remove(); });
    clone.querySelectorAll("rt").forEach(function (rt) {
      var ruby = rt.closest("ruby");
      if (ruby) {
        ruby.replaceWith(
          ruby.firstChild.textContent + "(" + rt.textContent + ")"
        );
      } else {
        rt.remove();
      }
    });
    return (clone.textContent || "").trim();
  }

  function copyBox(panel, box, withFurigana) {
    var text = withFurigana
      ? furiganaText(panel, box)
      : plainText(panel, box);
    if (!text) {
      toast("Nothing to copy yet", "info");
      return;
    }
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(function () {
        toast(withFurigana ? "Copied with furigana" : "Copied", "success");
      }, function () {
        toast("Could not copy", "error");
      });
      return;
    }
    // Plain HTTP on a LAN address has no clipboard API.
    var field = document.createElement("textarea");
    field.value = text;
    field.setAttribute("readonly", "");
    field.style.position = "absolute";
    field.style.left = "-9999px";
    document.body.appendChild(field);
    field.select();
    try {
      document.execCommand("copy");
      toast(withFurigana ? "Copied with furigana" : "Copied", "success");
    } catch (e) {
      toast(text, "info");
    }
    field.remove();
  }

  // ── copy menu ──────────────────────────────────────────────────

  function closeCopyMenus() {
    document.querySelectorAll("[data-copy-menu]").forEach(function (m) {
      m.classList.add("hidden");
    });
    document.querySelectorAll("[aria-expanded]").forEach(function (b) {
      if (b.getAttribute("aria-expanded") === "true") {
        b.setAttribute("aria-expanded", "false");
      }
    });
  }

  function toggleCopyMenu(button, panel) {
    var existing = button.parentNode.querySelector("[data-copy-menu]");
    if (existing && !existing.classList.contains("hidden")) {
      closeCopyMenus();
      return;
    }
    closeCopyMenus();
    var menu = $("jp-copy-template").content.firstElementChild.cloneNode(true);
    button.parentNode.appendChild(menu);
    menu.querySelector("[data-copy-plain]").addEventListener("click",
      function () {
        copyBox(panel, panel.result, false);
        closeCopyMenus();
      });
    menu.querySelector("[data-copy-furigana]").addEventListener("click",
      function () {
        copyBox(panel, panel.result, true);
        closeCopyMenus();
      });
    menu.classList.remove("hidden");
    button.setAttribute("aria-expanded", "true");
  }

  document.addEventListener("click", function (event) {
    if (!event.target.closest("[data-copy-menu]")
        && !event.target.closest("[id$=-copy-menu]")) {
      closeCopyMenus();
    }
  });

  function clearPanel(panel) {
    if (panel.timer) { clearTimeout(panel.timer); }
    panel.timer = null;
    panel.requestId += 1; // drop any response in flight
    panel.submitted = "";
    panel.selection = null;
    panel.input.value = "";
    panel.clear.classList.add("hidden");
    clearError(panel);
    resetResult(panel);
    saveToUrl(panel);
  }

  // ── wiring ─────────────────────────────────────────────────────

  function wirePanel(panelId, direction) {
    var panel = {
      id: panelId,
      direction: direction,
      input: $(panelId + "-input"),
      translate: $(panelId + "-translate"),
      loading: $(panelId + "-loading"),
      error: $(panelId + "-error"),
      // Express renders ruby on the result itself, so it has no separate
      // furigana element — everything touching these must allow null.
      furigana: $(panelId + "-furigana"),
      furiganaBlock: $(panelId + "-furigana-block"),
      result: $(panelId + "-result"),
      placeholder: $(panelId + "-result").dataset.placeholder || "",
      clear: $(panelId + "-clear"),
      timer: null,
      requestId: 0,
      submitted: "",
      selection: null,
    };
    panels[panelId] = panel;

    panel.input.addEventListener("input", function () {
      // The clear button only means something with text to clear.
      panel.clear.classList.toggle("hidden", !panel.input.value);
      panel.selection = null;
      // Editing marks the result as belonging to an earlier text until the
      // debounced translation replaces it.
      if (panel.submitted && panel.input.value.trim() !== panel.submitted) {
        panel.result.classList.add("jp-stale");
        if (panel.furigana) { panel.furigana.classList.add("jp-stale"); }
      } else {
        panel.result.classList.remove("jp-stale");
        if (panel.furigana) { panel.furigana.classList.remove("jp-stale"); }
      }
      scheduleTranslate(panel);
    });
    panel.input.addEventListener("keydown", function (event) {
      // Ctrl/Cmd+Enter skips the debounce; IME composition first.
      if (event.key === "Enter" && (event.ctrlKey || event.metaKey)
          && !event.isComposing) {
        event.preventDefault();
        if (panel.timer) { clearTimeout(panel.timer); }
        panel.timer = null;
        translate(panel);
      }
    });
    panel.translate.addEventListener("click", function () {
      if (panel.timer) { clearTimeout(panel.timer); }
      panel.timer = null;
      translate(panel);
    });
    panel.clear.addEventListener("click", function () {
      clearPanel(panel);
      panel.input.focus();
    });

    // Per-side audio. Input speakers read the input (selection-aware);
    // result speakers read the translation (selection-aware).
    $(panelId + "-input-speak").addEventListener("click", function () {
      speech.speak(this.id, speakableText(panel, "input"),
        panel.direction === "ja_en");
    });
    $(panelId + "-result-speak").addEventListener("click", function () {
      speech.speak(this.id, speakableText(panel, "result"),
        panel.direction === "en_ja");
    });
    $(panelId + "-input-rate").addEventListener("click", function () {
      this.textContent = speech.cycleRate();
    });
    $(panelId + "-result-rate").addEventListener("click", function () {
      this.textContent = speech.cycleRate();
    });
    $(panelId + "-input-copy").addEventListener("click", function () {
      copyBox(panel, panel.input, false);
    });
    $(panelId + "-result-copy").addEventListener("click", function () {
      copyBox(panel, panel.result, false);
    });

    // The chevron reveals the copy menu (plain vs with furigana) — only on
    // sides that carry furigana, where the two differ.
    var menuButton = $(panelId + "-result-copy-menu");
    if (menuButton) {
      menuButton.addEventListener("click", function (event) {
        event.stopPropagation();
        toggleCopyMenu(menuButton, panel);
      });
    }

    // A selection inside the panel is remembered (with its side) so the
    // speaker can still read it after the click collapses the selection.
    // New results drop it; changing text marks it stale via input handlers.
    document.addEventListener("selectionchange", function () {
      var text = selectionIn(panel.furigana)
        || selectionIn(panel.result);
      if (text) {
        panel.selection = { box: panel.result, text: text };
      }
    });
  }

  speech.init();
  wirePanel("jp-understand", "ja_en");
  wirePanel("jp-express", "en_ja");
  restorePassword();

  // Shared text in the URL (?ja=…&en=…) is filled in and translated at
  // once — that is the point of a shareable link.
  Object.keys(panels).forEach(function (id) {
    if (restoreFromUrl(panels[id])) {
      panels[id].clear.classList.remove("hidden");
      translate(panels[id]);
    }
  });

  var passwordField = $("jp-password");
  if (passwordField) {
    passwordField.addEventListener("change", rememberPassword);
  }

  // Leaving the page must not leave speech running.
  window.addEventListener("pagehide", function () { speech.stop(); });
})();
