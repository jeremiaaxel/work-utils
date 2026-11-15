/* vad.js — Silero VAD via transformers.js.
 *
 * Decides when the speaker has finished an utterance. Runs locally in the
 * page (audio never leaves). The state machine:
 *
 *   silence ──speech-start──▶ speech ──silence>hangover──▶ endpoint
 *
 * Segments are cut with pre-roll so the first syllable is not clipped
 * (manifest §14.4), bounded in length so a long monologue is transcribed
 * in pieces rather than never, and fed to the caller as 16 kHz Float32.
 */

import { pipeline, env } from "@huggingface/transformers";

env.allowLocalModels = false;

export const SAMPLE_RATE = 16000;

// Tuned for conversational pauses (P1 will expose these in the UI).
const START_THRESHOLD = 0.5;   // speech probability to open a segment
const END_THRESHOLD = 0.35;    // probability below which we count silence
const END_HANGOVER_MS = 350;   // silence this long closes a segment
const MIN_SPEECH_MS = 250;     // shorter bursts are noise; drop
const MAX_SEGMENT_MS = 15000;  // force a cut at this length
const PREROLL_MS = 250;        // audio before speech-start kept for context

export async function initialize(progress) {
  return pipeline("audio-classification", "onnx-community/silero-vad", {
    dtype: "q8",
    progress_callback: progress,
  });
}

/**
 * Segmenter: feed raw 16 kHz Float32 chunks (any size), receive completed
 * utterance segments. Purely local, no network.
 */
export function createSegmenter(vadPipe, onSegment) {
  var sample = 0;              // absolute sample position
  var buf = [];                // current segment samples (incl. pre-roll)
  var inSpeech = false;
  var silenceMs = 0;
  var speechMs = 0;
  var prerollSamples = Math.round((PREROLL_MS / 1000) * SAMPLE_RATE);
  var preroll = [];

  // Buffer the VAD's own input window: silero wants ~512-sample frames.
  var pending = new Float32Array(0);
  var FRAME = 512;

  function emit() {
    if (buf.length >= (MIN_SPEECH_MS / 1000) * SAMPLE_RATE) {
      onSegment(Float32Array.from(buf));
    }
    buf = [];
    preroll = [];
    inSpeech = false;
    silenceMs = 0;
    speechMs = 0;
  }

  async function drainFrame() {
    while (pending.length >= FRAME) {
      var frame = pending.subarray(0, FRAME);
      pending = pending.slice(FRAME);
      var result;
      try {
        var out = await vadPipe(frame, { sampling_rate: SAMPLE_RATE });
        result = out && out[0] ? out[0].score : 0;
      } catch (e) {
        result = 0;
      }
      sample += FRAME;
      var frameMs = (FRAME / SAMPLE_RATE) * 1000;

      if (!inSpeech) {
        preroll.push(frame.slice());
        if (preroll.length * frameMs > PREROLL_MS * 3) { preroll.shift(); }
        if (result >= START_THRESHOLD) {
          inSpeech = true;
          speechMs = frameMs;
          silenceMs = 0;
          buf = [];
          preroll.forEach(function (f) {
            for (var i = 0; i < f.length; i++) { buf.push(f[i]); }
          });
          preroll = [];
        }
        continue;
      }

      for (var j = 0; j < frame.length; j++) { buf.push(frame[j]); }
      speechMs += frameMs;
      if (result < END_THRESHOLD) {
        silenceMs += frameMs;
        if (silenceMs >= END_HANGOVER_MS) { emit(); continue; }
      } else {
        silenceMs = 0;
      }
      if (speechMs >= MAX_SEGMENT_MS) { emit(); }
    }
  }

  return {
    /** Feed one AudioWorklet chunk (Float32, 16 kHz). */
    async feed(chunk) {
      var merged = new Float32Array(pending.length + chunk.length);
      merged.set(pending);
      merged.set(chunk, pending.length);
      pending = merged;
      if (inSpeech) {
        // Keep unbuffered audio even ahead of the VAD's verdicts so the
        // segment is continuous; drainFrame trims via pending anyway.
        for (var i = 0; i < chunk.length; i++) { buf.push(chunk[i]); }
      }
      await drainFrame();
    },
    /** Force-close any open segment (Stop pressed, page hidden). */
    flush() {
      if (inSpeech) { emit(); }
    },
  };
}
