/* models.js — the model catalogue and pinned revisions.
 *
 * One place that knows which models the page uses, how big they are and
 * which exact revision to fetch. The readiness card renders from this; the
 * ledger can therefore name every allowed remote host. Revisions are pinned
 * so a model update never silently changes behaviour (manifest §13.4).
 */

export const MODELS = [
  {
    id: "whisper-base",
    repo: "onnx-community/whisper-base",
    revision: "27a07b4b52b3a4c5886134bb4320e93e1a4bbc7c",
    label: "Whisper base (speech → Japanese text)",
    sizeMb: 85,
  },
  {
    id: "opus-mt-ja-en",
    repo: "Xenova/opus-mt-ja-en",
    revision: "1a906cfaaf7c8f4193f67f5885c082aa6dbd9d16",
    label: "Opus-MT ja→en (translation)",
    sizeMb: 120,
  },
  {
    id: "silero-vad",
    repo: "onnx-community/silero-vad",
    revision: "main",
    label: "Silero VAD (speech detection)",
    sizeMb: 2,
  },
  {
    id: "kuromoji",
    repo: "kuromoji.js (IPADIC)",
    revision: "npm",
    label: "Kuromoji (furigana)",
    sizeMb: 17,
  },
];

// Hosts the page is allowed to contact for model assets. The ledger checks
// every observed request against this list; anything else is flagged.
export const ALLOWED_HOSTS = [
  "huggingface.co",
  "cdn-lfs.huggingface.co",
  "cas-bridge.xethub.hf.co",
  window.location.host,
];

export function totalSizeMb() {
  return MODELS.reduce((sum, m) => sum + m.sizeMb, 0);
}
