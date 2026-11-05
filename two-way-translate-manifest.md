# Implementation Manifest: Japanese Learning View

## 1. Objective

Build the equivalent of two translation tabs in one page, with furigana and optional pronunciation playback:

1. **Understand — Japanese → English**
   - Japanese input.
   - Japanese with furigana.
   - English translation.
2. **Express — English → Japanese**
   - English input.
   - Japanese translation with furigana.

Users can select a Japanese expression and listen to its pronunciation without leaving the page.

This is a text-based learning tool, not a conversation translator. Speech recognition and microphone capture are out of scope.

## 2. Engineering principles

- **KISS:** solve the actual user problem with the smallest reliable implementation.
- **DRY:** share rendering and service logic, but keep panel state independent.
- Inspect the existing application before adding dependencies.
- Briefly compare practical alternatives and justify the chosen approach.
- Reuse the existing design system, authentication, and translation backend.
- Do not introduce distributed infrastructure for a UI problem.
- Verify API/library capabilities rather than inventing them.
- Apply relevant best practices without unnecessary abstraction.

## 3. Inspect before coding

Locate:

- Frontend framework, routes, components, and styles.
- Translation backend and supported language directions.
- Existing Japanese reading-analysis functionality.
- Authentication and authorization.
- State persistence and caching.
- Existing tests.

Deliver a short plan containing:

1. Actual files/functions to change.
2. Alternatives considered.
3. Selected approach and tradeoffs.
4. Important unknowns.

Then implement incrementally.

## 4. Scope

### Required

- Two independent translation panels.
- Fixed language directions.
- Furigana above kanji.
- Selectable and copyable Japanese.
- Show/hide furigana.
- Independent inputs, results, loading, and errors.
- Preserve both panels while using the page.
- Responsive and accessible layout.

### Optional enhancement: pronunciation

- Listen to selected Japanese.
- Listen to an entire Japanese result when no text is selected.
- Stop playback.
- Playback-rate control.
- Graceful fallback if Japanese speech is unavailable.

### Out of scope

- Speech recognition or conversation mode.
- OCR changes.
- Anki integration.
- Grammar tutoring.
- New authentication systems.
- Unnecessary provider migration.
- New queues, microservices, or serverless infrastructure.
- Extensive history management.
- Full furigana-correction editor.

## 5. Layout and interaction

### Default layout

Use two vertically stacked panels:

Understand · Japanese → English
[Japanese input]
[Translate]

Japanese with furigana
English translation
[Listen] [Stop] [Copy Japanese]

────────────────────────────

Express · English → Japanese
[English input]
[Translate]

Japanese translation with furigana
[Listen] [Stop] [Copy Japanese]

### Compare layout alternatives briefly

- **Stacked:** clear reading order and mobile compatibility; requires scrolling.
- **Side by side:** useful on wide screens; narrower text and competing information.
- **Tabs:** compact, but hides one direction and recreates switching friction.

Preferred: stacked. Do not add a layout selector without a demonstrated need.

### Reduce cognitive load

- Use “Understand” and “Express” plus explicit language directions.
- One primary action per panel: Translate.
- No language-swap control.
- Use whitespace and headings before introducing more colors.
- Follow the existing design system.
- Use accent colors sparingly.
- Keep audio controls visually secondary.
- Show errors and loading only in the affected panel.
- Avoid permanently visible advanced settings.

### Input and annotated text

Compare:

1. Textarea plus an annotated reading view.
2. Ruby-enabled rich-text editor.

Prefer the textarea plus reading view for the MVP. A custom editor adds Japanese IME and selection complexity.

### Behavior

- Translate buttons act independently.
- Support Ctrl/Cmd + Enter within the focused panel.
- Do not submit during IME composition.
- Editing one panel must not affect the other.
- Preserve the last successful result while updating.
- Identify results that belong to an earlier input.
- Furigana toggling must not call translation.
- Copy Japanese excludes furigana readings.
- Do not autoplay pronunciation.

## 6. Translation

Reuse the existing backend where possible:

- Understand: ja → en.
- Express: en → ja.

Do not embed or reverse-proxy the Google Translate website.

Document provider limitations, including reliability concerns for unofficial services.

Requirements:

- Bound input length and request timeouts.
- Prevent accidental duplicate submissions.
- Cancel superseded requests where supported.
- Ignore stale responses.
- Keep provider credentials on the server.
- Preserve existing authentication and authorization.

Do not introduce background jobs unless measured processing duration requires them.

## 7. Furigana

Translation and reading annotation are separate operations:

- Understand: annotate the Japanese input.
- Express: annotate the Japanese translation.

### Dependency selection

Inspect existing tools first. Compare:

- Existing Japanese analyzer.
- Maintained local tokenizer/dictionary.
- External reading service.

Consider:

- Accuracy.
- Licensing.
- Memory and startup cost.
- Maintenance.
- Privacy.
- Dependency size.

Prefer an existing/local solution when practical.

### Rendering

Use HTML ruby:

<ruby>日本語<rt>にほんご</rt></ruby>

Requirements:

- Readings displayed in hiragana.
- Kana-only text remains unannotated.
- Preserve punctuation, whitespace, and text order.
- Prefer reliable whole-word annotations over fragile character alignment.
- Render structured text safely, not untrusted HTML.
- Reading-analysis failures must not hide Japanese or translation.
- Names and ambiguous words may receive incorrect readings.
- Keep the data model compatible with future reading corrections.

Suggested token shape:

[
  {"text": "日本語", "reading": "にほんご"},
  {"text": "を", "reading": null},
  {"text": "学ぶ", "reading": "まなぶ"}
]

Concatenating token text must reconstruct the source Japanese exactly.

## 8. Selected-expression pronunciation

### Business requirement

The user highlights a Japanese word or expression and clicks Listen to hear it.

This is text-to-speech playback, not microphone listening.

### Compare approaches

1. **Browser speech synthesis**
   - No new backend required.
   - Low implementation and operating cost.
   - Voice availability and quality vary by browser/OS.
   - Some voices may use network services.

2. **Server/provider TTS**
   - More consistent voices.
   - Adds cost, latency, credentials, privacy considerations, and maintenance.

Preferred MVP: browser SpeechSynthesis API, subject to actual Japanese-voice availability.

Do not add server TTS unless browser playback is insufficient.

### Selection behavior

1. Support Japanese text in:
   - Understand input.
   - Understand annotated view.
   - Express Japanese output.
2. For textarea selection, use selectionStart/selectionEnd.
3. For rendered text, capture selection only within the relevant Japanese container.
4. Speak selected Japanese when a valid non-empty selection exists.
5. Otherwise speak the panel’s current Japanese text.
6. Do not accidentally use selected English or text from another panel.
7. Preserve the selection before clicking Listen causes focus changes.
8. Clear stored selection when its text/result changes.

### Ruby handling

Do not speak both base text and furigana.

Rendered selection may include rt/rp content. Do not assume
window.getSelection().toString() always gives clean Japanese.

Prefer mapping the selection to canonical source text. If that is too complex:

- Restrict selection to the panel.
- Extract the selected fragment.
- Remove rt/rp elements.
- Normalize the resulting text.
- Test selection boundaries around ruby.

Copy Japanese should use the same canonical-text logic.

### Playback behavior

- Feature-detect speechSynthesis and SpeechSynthesisUtterance.
- Discover available voices.
- Handle voices loading asynchronously through voiceschanged.
- Prefer a voice whose language is ja or ja-*.
- Set utterance language to ja-JP.
- Do not use an arbitrary non-Japanese voice as a silent fallback.
- Show unavailable/loading states clearly.
- Start playback only from an explicit user action.
- Cancel existing playback before starting another utterance.
- Provide Stop.
- Use one shared speech controller; do not play both panels simultaneously.
- Stop when leaving the page.
- Track start/end/error states.
- Do not promise accurate pronunciation for every name or ambiguous word.
- Do not assume playback is offline.

### Controls

Use compact secondary controls:

[Listen to selection / Listen] [Stop] [Speed]

Proposed speed presets:

- 0.8×
- 1.0×
- 1.2×

Speech rates are approximate; behavior depends on the speech engine.

Do not add voice-selection UI initially unless multiple available voices create a real need.

### Fallback

If no suitable Japanese voice is available:

- Keep translation and furigana fully usable.
- Disable playback with a concise explanation.
- Do not silently send text to a new external TTS service.
- Document the tested browser/OS behavior.

## 9. Code organization and state

Share:

- TranslationPanel component.
- API client.
- RubyText renderer.
- Reading-analysis adapter.
- Speech controller.
- Loading/error presentation.
- Canonical Japanese extraction for copy/playback.

Keep separate per panel:

- Input.
- Submitted-input snapshot.
- Output.
- Annotation.
- Loading.
- Error.
- Latest request ID.
- Valid selected-expression snapshot.

Avoid duplicated full components and large generic frameworks.

## 10. Persistence and privacy

Required: preserve both panels while interacting with the page.

For reload persistence, compare existing storage, sessionStorage,
and localStorage. Choose the minimum necessary behavior.

- Storage failures must not crash the UI.
- Do not introduce credential persistence.
- Avoid indefinite draft retention without a reason.
- Consider shared/work-browser privacy.
- Provide Clear if drafts are persisted.
- Do not log full entered text or selected expressions by default.

## 11. Accessibility

- Semantic headings and explicit labels.
- Visible keyboard focus.
- WCAG AA contrast.
- Sufficient line spacing for ruby.
- No state communicated by color alone.
- Accessible names for audio controls.
- No automatic focus stealing.
- Restrained live announcements.
- Stop playback remains easy to reach.
- Controls remain usable on narrow screens.

## 12. Tests and acceptance criteria

### Translation and reading

- Both directions work without extra tabs.
- Panel states are independent.
- Furigana annotates the correct Japanese text.
- Toggle does not translate again.
- Copy excludes readings.
- Annotation failure preserves translation.
- Stale responses cannot overwrite newer results.
- Storage unavailability does not crash the page.

### Japanese input cases

- Kanji-only words.
- Mixed kanji/kana.
- Kana-only sentences.
- Names/unknown words.
- Punctuation and line breaks.
- Empty/whitespace-only input.
- IME composition.

### Audio

- Selected Japanese is spoken instead of the full result.
- No selection speaks the relevant full Japanese text.
- Textarea selection works.
- Ruby selection does not duplicate readings.
- English selection is ignored.
- Selection survives clicking Listen.
- Changed text invalidates stored selection.
- New playback stops previous playback.
- Stop works.
- Voice discovery works when initially empty.
- Missing API or Japanese voice has a graceful fallback.
- Playback errors do not affect translation.
- Leaving the page cancels playback.

### UI

- Responsive on narrow/wide screens.
- Ruby does not overlap adjacent lines.
- Keyboard focus is clear.
- Loading/errors remain local to the panel.
- Japanese is selectable for dictionary tools.
- Extension compatibility is tested, not assumed.

## 13. Delivery

Provide:

1. Short alternatives/tradeoffs and chosen approach.
2. Changed files and rationale.
3. New dependencies, if any.
4. Tests and results.
5. Manual verification instructions.
6. Tested browser/OS for speech.
7. Known limitations.

Definition of done:

The user can understand Japanese and express ideas in Japanese in one
uncluttered page, see kanji readings, and optionally hear selected
expressions without opening additional tabs.

## 14. References and uncertainty

This is an implementation proposal, not a benchmark.

Reading accuracy and speech quality depend on the analyzer, browser,
operating system, and available voices.

- Ruby:
  https://developer.mozilla.org/en-US/docs/Web/HTML/Element/ruby
- Speech synthesis:
  https://developer.mozilla.org/en-US/docs/Web/API/SpeechSynthesis
- Voice discovery:
  https://developer.mozilla.org/en-US/docs/Web/API/SpeechSynthesis/voiceschanged_event
- Text selection:
  https://developer.mozilla.org/en-US/docs/Web/API/Window/getSelection
- IME composition:
  https://developer.mozilla.org/en-US/docs/Web/API/Element/compositionstart_event
- Accessibility:
  https://www.w3.org/WAI/WCAG22/quickref/

