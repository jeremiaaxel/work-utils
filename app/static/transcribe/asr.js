/* asr.js — the Transcriber: whisper-base via transformers.js.
 *
 * Wraps the model behind the manifest's Transcriber interface
 * (initialize / transcribe / dispose) so orchestration never touches
 * transformers.js directly and a future backend could swap in behind the
 * same calls. Everything runs in this tab; nothing is uploaded.
 */

import { pipeline, env } from "@huggingface/transformers";

// Models come from the pinned revisions (see models.js); no telemetry.
env.allowLocalModels = false;

const REVISION = "27a07b4b52b3a4c5886134bb4320e93e1a4bbc7c";

let transcriber = null; // the loaded pipeline (null = not initialized)

export function isReady() {
  return transcriber !== null;
}

/** Download/initialize. `progress` receives {file, progress, loaded, total}. */
export async function initialize(progress) {
  if (transcriber) { return transcriber; }
  transcriber = await pipeline(
    "automatic-speech-recognition",
    "onnx-community/whisper-base",
    {
      dtype: "q8",
      revision: REVISION,
      progress_callback: progress,
    },
  );
  return transcriber;
}

/** Transcribe one utterance's Float32 PCM (16 kHz mono) to Japanese text. */
export async function transcribe(audioFloat32) {
  if (!transcriber) {
    throw new Error("Transcriber not initialized");
  }
  const out = await transcriber(audioFloat32, {
    language: "japanese",
    task: "transcribe",
    chunk_length_s: 30,
    stride_length_s: 5,
  });
  return (out && out.text ? out.text : "").trim();
}

export function dispose() {
  transcriber = null;
}
