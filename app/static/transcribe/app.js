/* app.js — JP Transcribe orchestrator.
 *
 * Owns the session state machine and wires the pieces together:
 *
 *   mic (getUserMedia + AudioWorklet resampler)
 *     → vad.js segmenter (local)
 *     → asr.js whisper (local)
 *     → mt.js opus-mt (local)
 *     → furigana.js kuromoji (local)
 *     → transcript DOM
 *
 * The transcript lives only in this page's memory. There is no server
 * endpoint to send it to; the ledger watches that this stays true.
 * Segment IDs are stable (monotonic) so a future remote backend could emit
 * the same events (manifest §17).
 */

import { startLedger } from "./ledger.js";
import { MODELS, totalSizeMb } from "./models.js";
import * as asr from "./asr.js";
import * as mt from "./mt.js";
import * as furigana from "./furigana.js";
import { initialize as vadInit, createSegmenter, SAMPLE_RATE } from "./vad.js";

const READY_STEPS = [
  { id: "whisper-base", run: asr.initialize },
  { id: "opus-mt-ja-en", run: mt.initialize },
  { id: "silero-vad", run: vadInit },
  { id: "kuromoji", run: furigana.initialize },
];

const state = {
  phase: "unprepared", // unprepared | preparing | ready | recording | paused
  micStream: null,
  audioContext: null,
  workletNode: null,
  segmenter: null,
  segmentSeq: 0,
  paused: false,
  follow: true, // auto-scroll while the reader is near the bottom
};

// ── small DOM helpers ──────────────────────────────────────────────

function $(id) { return document.getElementById(id); }

function setBadge(text, cls) {
  var badge = $("tr-privacy-badge");
  if (!badge) { return; }
  badge.textContent = text;
  badge.className = cls || "badge badge-ghost";
}

function setRecDot(live) {
  var dot = $("tr-rec-dot");
  if (dot) { dot.dataset.live = String(live); }
}

function setStateText(text) {
  var el = $("tr-state-text");
  if (el) { el.textContent = text; }
}

function setButtons() {
  var started = state.phase === "recording" || state.phase === "paused";
  if ($("tr-start")) { $("tr-start").disabled = state.phase !== "ready"; }
  if ($("tr-pause")) { $("tr-pause").disabled = !started; }
  if ($("tr-stop")) { $("tr-stop").disabled = !started; }
  if ($("tr-clear")) { $("tr-clear").disabled = $("tr-transcript").childElementCount === 0; }
}

// ── readiness card (manifest §13) ──────────────────────────────────

function renderModelList() {
  var list = $("tr-model-list");
  if (!list) { return; }
  list.innerHTML = MODELS.map(function (m, i) {
    return (
      "<div class='flex items-center gap-2 text-sm py-0.5'>" +
      "<span class='font-mono text-xs opacity-60'>" + (i + 1) + "</span>" +
      "<span class='flex-1'>" + m.label + "</span>" +
      "<span class='opacity-60 text-xs'>" + m.sizeMb + " MB</span>" +
      "<span id='tr-status-" + m.id + "' class='badge badge-ghost badge-sm'>queued</span>" +
      "</div>"
    );
  }).join("") +
  "<div class='text-xs opacity-60 mt-1'>Total ≈ " + totalSizeMb() +
  " MB, downloaded once into this browser's cache.</div>";
}

function modelStatus(id, text, cls) {
  var el = $("tr-status-" + id);
  if (!el) { return; }
  el.textContent = text;
  el.className = "badge badge-sm " + (cls || "badge-ghost");
}

// One model row at a time; transformers.js reports per-file progress.
async function prepare() {
  if (state.phase !== "unprepared") { return; }
  state.phase = "preparing";
  var btn = $("tr-prepare-btn");
  if (btn) { btn.disabled = true; }
  setBadge("⏳ Loading models…", "badge badge-warning");
  for (var i = 0; i < READY_STEPS.length; i++) {
    var step = READY_STEPS[i];
    modelStatus(step.id, "downloading…", "badge-warning");
    try {
      await step.run(function (p) {
        if (p && typeof p.progress === "number" && p.file && /\.onnx$/.test(p.file)) {
          modelStatus(step.id, Math.round(p.progress) + "%", "badge-warning");
        }
      });
      modelStatus(step.id, "cached ✓", "badge-success");
    } catch (err) {
      modelStatus(step.id, "failed", "badge-error");
      setBadge("⚠ Model load failed — see console", "badge badge-error");
      state.phase = "unprepared";
      if (btn) { btn.disabled = false; }
      console.error("model load failed:", step.id, err);
      return;
    }
  }
  // Cached → in memory → ready: at this point every pipeline is loaded.
  await selfTest();
}

// Microphone + inference self-test (manifest §13.6): record ≤2 s of audio,
// transcribe it locally, show the result. Start stays locked until this
// passes, so "recording" never begins on a broken pipeline.
async function selfTest() {
  setBadge("🎙 Self-test: speak for two seconds…", "badge badge-info");
  var text = "";
  try {
    var stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
    });
    text = await recordSample(stream, 2000);
    stream.getTracks().forEach(function (t) { t.stop(); });
    text = text || "(heard nothing — mic muted or too quiet)";
    var ja = await asr.transcribe(text);
    ja = ja || "(no speech detected)";
    setBadge("✓ Self-test heard: " + ja.slice(0, 60), "badge badge-success");
  } catch (err) {
    setBadge("⚠ Self-test failed — see console", "badge badge-error");
    console.error("self-test failed", err);
    state.phase = "unprepared";
    var btn = $("tr-prepare-btn");
    if (btn) { btn.disabled = false; }
    return;
  }
  state.phase = "ready";
  setBadge("🔒 On this device — audio & text never leave this browser",
    "badge badge-success");
  // Swap the readiness card for the live view.
  $("tr-readiness").classList.add("hidden");
  $("tr-live").classList.remove("hidden");
  setButtons();
}

/** One bounded recording; returns 16 kHz Float32 (resampled below). */
function recordSample(stream, ms) {
  return new Promise(async function (resolve) {
    var ctx = new AudioContext({ sampleRate: SAMPLE_RATE });
    var src = ctx.createMediaStreamSource(stream);
    // A ScriptProcessor is fine for the two-second self-test; the real
    // session uses an AudioWorklet.
    var proc = ctx.createScriptProcessor(4096, 1, 1);
    var chunks = [];
    proc.onaudioprocess = function (e) {
      chunks.push(new Float32Array(e.inputBuffer.getChannelData(0)));
    };
    src.connect(proc);
    // Gain to nowhere keeps the graph pulling in Chrome's muted-tab case.
    var sink = ctx.createGain();
    sink.gain.value = 0;
    proc.connect(sink);
    sink.connect(ctx.destination);
    setTimeout(function () {
      proc.disconnect(); src.disconnect();
      ctx.close();
      var total = chunks.reduce(function (n, c) { return n + c.length; }, 0);
      var all = new Float32Array(total);
      var off = 0;
      chunks.forEach(function (c) { all.set(c, off); off += c.length; });
      resolve(all);
    }, ms);
  });
}

// ── microphone session ─────────────────────────────────────────────

const RESAMPLER_WORKLET = `
class ResampleWorklet extends AudioWorkletProcessor {
  constructor() { super(); this.ratio = sampleRate / ${SAMPLE_RATE}; this.carry = 0; }
  process(inputs) {
    const input = inputs[0][0];
    if (!input) { return true; }
    const out = [];
    const step = this.ratio;
    let pos = this.carry;
    while (pos < input.length) { out.push(input[Math.floor(pos)] || 0); pos += step; }
    this.carry = pos - input.length;
    this.port.postMessage(Float32Array.from(out));
    return true;
  }
}
registerProcessor("resample-worklet", ResampleWorklet);
`;

async function startRecording() {
  if (state.phase !== "ready") { return; }
  try {
    state.micStream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
    });
  } catch (err) {
    setBadge("⚠ Microphone permission denied", "badge badge-error");
    return;
  }
  state.audioContext = new AudioContext({ sampleRate: SAMPLE_RATE });
  await state.audioContext.audioWorklet.addModule(
    URL.createObjectURL(new Blob([RESAMPLER_WORKLET], { type: "application/javascript" }))
  );
  var src = state.audioContext.createMediaStreamSource(state.micStream);
  state.workletNode = new AudioWorkletNode(state.audioContext, "resample-worklet");
  state.segmenter = createSegmenter(await vadInit(null), onUtterance);
  state.workletNode.port.onmessage = async function (event) {
    if (state.paused || state.phase !== "recording") { return; }
    await state.segmenter.feed(event.data);
  };
  src.connect(state.workletNode);
  // Silent sink keeps the graph running when the tab is muted.
  var sink = state.audioContext.createGain();
  sink.gain.value = 0;
  state.workletNode.connect(sink);
  sink.connect(state.audioContext.destination);

  state.phase = "recording";
  state.paused = false;
  setRecDot(true);
  setStateText("Recording — on this device");
  setBadge("⏺ Recording locally", "badge badge-success");
  setButtons();
}

async function pause() {
  if (state.phase !== "recording") { return; }
  state.paused = true;
  state.phase = "paused";
  await state.segmenter.flush();
  setRecDot(false);
  setStateText("Paused — microphone open, VAD suspended");
  setBadge("⏸ Paused (mic still open)", "badge badge-warning");
  setButtons();
}

async function resume() {
  if (state.phase !== "paused") { return; }
  state.paused = false;
  state.phase = "recording";
  setRecDot(true);
  setStateText("Recording — on this device");
  setBadge("⏺ Recording locally", "badge badge-success");
  setButtons();
}

async function stop() {
  if (state.phase !== "recording" && state.phase !== "paused") { return; }
  try { await state.segmenter.flush(); } catch (e) { /* nothing open */ }
  if (state.workletNode) { state.workletNode.port.onmessage = null; }
  if (state.micStream) {
    state.micStream.getTracks().forEach(function (t) { t.stop(); });
    state.micStream = null;
  }
  if (state.audioContext) {
    try { await state.audioContext.close(); } catch (e) { /* already closed */ }
    state.audioContext = null;
  }
  state.workletNode = null;
  state.segmenter = null;
  state.phase = "ready";
  setRecDot(false);
  setStateText("Stopped — microphone released");
  setBadge("🔒 On this device — audio & text never leave this browser",
    "badge badge-success");
  setButtons();
}

function clearSession() {
  var box = $("tr-transcript");
  if (box) { box.innerHTML = ""; }
  state.segmentSeq = 0;
  setButtons();
}

// ── utterance pipeline ─────────────────────────────────────────────

function buildSegmentDom(seq) {
  var scroll = $("tr-transcript-scroll");
  var box = $("tr-transcript");
  var seg = document.createElement("div");
  seg.id = "tr-seg-" + seq;
  seg.className = "rounded-lg bg-base-100 p-3 shadow-sm";
  seg.innerHTML =
    "<div class='text-xs opacity-50 mb-1'>#" + seq + "</div>" +
    "<div class='tr-ja text-lg leading-loose' data-kind='ja'></div>" +
    "<div class='tr-en mt-1' data-kind='en'></div>";
  box.appendChild(seg);
  maybeScroll();
  return {
    root: seg,
    ja: seg.querySelector("[data-kind=ja]"),
    en: seg.querySelector("[data-kind=en]"),
  };
}

function maybeScroll() {
  var scroll = $("tr-transcript-scroll");
  if (!scroll || !state.follow) { return; }
  scroll.scrollTop = scroll.scrollHeight;
}

function wireFollow() {
  var scroll = $("tr-transcript-scroll");
  var btn = $("tr-resume-follow");
  if (!scroll || !btn) { return; }
  scroll.addEventListener("scroll", function () {
    var atBottom = scroll.scrollHeight - scroll.scrollTop - scroll.clientHeight < 40;
    state.follow = atBottom;
    btn.classList.toggle("hidden", atBottom);
  });
  btn.addEventListener("click", function () {
    state.follow = true;
    scroll.scrollTop = scroll.scrollHeight;
  });
}

/** One finished utterance: transcribe → translate → annotate, locally. */
async function onUtterance(pcm) {
  var seq = ++state.segmentSeq;
  var dom = buildSegmentDom(seq);
  dom.ja.classList.add("tr-provisional");
  dom.ja.textContent = "…";

  var jaText = "";
  try {
    jaText = await asr.transcribe(pcm);
  } catch (err) {
    console.error("transcription failed", err);
    dom.ja.textContent = "(transcription failed — segment kept locally)";
    dom.ja.classList.remove("tr-provisional");
    return;
  }
  if (!jaText) {
    dom.root.remove();
    return;
  }
  // Show Japanese immediately (manifest §15: furigana must not block it).
  dom.ja.textContent = jaText;
  maybeScroll();

  // Translation, provisional until it lands.
  try {
    var en = await mt.translate(jaText);
    dom.en.textContent = en || "(no translation)";
  } catch (err) {
    console.error("translation failed", err);
    dom.en.textContent = "(translation failed — text stays local)";
  }
  dom.ja.classList.remove("tr-provisional");
  setButtons();
  maybeScroll();

  // Furigana upgrades in place, never blocking the text above.
  try {
    dom.ja.innerHTML = furigana.toRubyHtml(jaText);
  } catch (err) {
    /* plain text already shown; furigana is enhancement only */
  }
}

// ── wiring ─────────────────────────────────────────────────────────

function wire() {
  startLedger();
  renderModelList();
  wireFollow();
  var prepareBtn = $("tr-prepare-btn");
  if (prepareBtn) { prepareBtn.addEventListener("click", prepare); }
  $("tr-start").addEventListener("click", startRecording);
  $("tr-pause").addEventListener("click", function () {
    if (state.phase === "paused") { resume(); } else { pause(); }
  });
  $("tr-stop").addEventListener("click", stop);
  $("tr-clear").addEventListener("click", clearSession);
  // Leaving the page must release the microphone (manifest §14: Stop
  // releases tracks; the same applies to the tab going away).
  window.addEventListener("pagehide", function () {
    if (state.micStream) {
      state.micStream.getTracks().forEach(function (t) { t.stop(); });
    }
    if (state.audioContext) { state.audioContext.close(); }
  });
}

wire();
