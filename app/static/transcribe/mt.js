/* mt.js — the Translator: Opus-MT ja→en via transformers.js.
 *
 * The manifest's Translator interface (initialize / translate / dispose).
 * Local only — there is deliberately no server fallback: if this model
 * fails, the UI reports the limitation instead of quietly uploading text
 * (manifest §11: no cloud fallback).
 */

import { pipeline, env } from "@huggingface/transformers";

env.allowLocalModels = false;

const REVISION = "1a906cfaaf7c8f4193f67f5885c082aa6dbd9d16";

let translator = null;

export function isReady() {
  return translator !== null;
}

export async function initialize(progress) {
  if (translator) { return translator; }
  translator = await pipeline(
    "translation",
    "Xenova/opus-mt-ja-en",
    {
      dtype: "q8",
      revision: REVISION,
      progress_callback: progress,
    },
  );
  return translator;
}

/** Japanese text in, English text out. */
export async function translate(text) {
  if (!translator) {
    throw new Error("Translator not initialized");
  }
  const out = await translator(text, { max_new_tokens: 256 });
  const first = Array.isArray(out) ? out[0] : out;
  return (first && first.translation_text ? first.translation_text : "").trim();
}

export function dispose() {
  translator = null;
}
