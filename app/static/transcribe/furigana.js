/* furigana.js — the ReadingAnnotator: kuromoji.js, fully local.
 *
 * The server's pykakasi path is off-limits here (it would send text to the
 * server, which the manifest forbids in local mode). kuromoji tokenizes
 * with IPADIC in the browser and its tokens carry readings; this converts
 * them to the same kanji(furigana) shape the copy menu uses, and to ruby
 * HTML matching app/core/japanese.py's output shape.
 *
 * Furigana never blocks transcription: annotate() is fire-and-forget — the
 * segment renders plain first and is upgraded in place when annotations
 * arrive (manifest §15).
 */

import kuromoji from "kuromoji";

let tokenizer = null;
let loading = null;

export function isReady() {
  return tokenizer !== null;
}

export async function initialize(onProgress) {
  if (tokenizer) { return tokenizer; }
  if (loading) { return loading; }
  loading = new Promise(function (resolve, reject) {
    kuromoji
      .builder({ dicPath: "/static/transcribe/dict/" })
      .build(function (err, built) {
        if (err) { reject(err); } else { tokenizer = built; resolve(built); }
      });
  });
  // kuromoji's loader has no progress callback we can trust; the model
  // list shows the dictionary size up front instead.
  void onProgress;
  try {
    return await loading;
  } finally {
    loading = null;
  }
}

/* Tokenize to {surface, reading} pairs; reading in hiragana where known. */
export function tokens(text) {
  if (!tokenizer) { return []; }
  return tokenizer.tokenize(text).map(function (t) {
    return {
      surface: t.surface_form,
      // IPADIC gives katakana readings; hiragana reads better as furigana.
      reading: toHiragana(t.reading || t.surface_form),
      base: t.basic_form || t.surface_form,
    };
  });
}

function toHiragana(katakana) {
  // Shift katakana codepoints into hiragana (u+30A1..u+30F6 -> u+3041..).
  return katakana.replace(/[ァ-ヶ]/g, function (ch) {
    return String.fromCharCode(ch.charCodeAt(0) - 0x60);
  });
}

const KANJI_RE = /[一-鿿㐀-䶿々]/;

/** Ruby HTML for one segment; falls back to plain text when not ready. */
export function toRubyHtml(text) {
  var toks = tokens(text);
  if (!toks.length) { return escapeHtml(text); }
  var out = "";
  toks.forEach(function (t) {
    var surface = escapeHtml(t.surface);
    if (KANJI_RE.test(t.surface) && t.reading && t.reading !== t.surface) {
      out +=
        "<ruby>" + surface + "<rp>(</rp><rt>" + escapeHtml(t.reading) +
        "</rt><rp>)</rp></ruby>";
    } else {
      out += surface;
    }
  });
  return out;
}

/** Plain kanji(furigana) form, matching jp-translator's copy output. */
export function toFuriganaText(text) {
  var toks = tokens(text);
  if (!toks.length) { return text; }
  return toks
    .map(function (t) {
      if (KANJI_RE.test(t.surface) && t.reading && t.reading !== t.surface) {
        return t.surface + "(" + t.reading + ")";
      }
      return t.surface;
    })
    .join("");
}

function escapeHtml(s) {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
