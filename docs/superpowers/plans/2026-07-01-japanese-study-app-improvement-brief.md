# Japanese Study App — Implementation Brief

## 1. Context and objective

Improve an existing personal Japanese page-study web app.

**Current stack:**
- FastAPI.
- TaskIQ background workers.
- PaddleOCR.
- Single server: **2 CPU cores, 4 GB RAM**.

**User workflow:**
1. Android captures and uploads a book page.
2. The PC browser opens the website.
3. The user views the original image, selectable Japanese, translations, and study operations.

**Problems to address:**
- Processing is slow, but the bottleneck is unknown.
- Images can be sideways, tilted, photographed at an angle, or curved near the spine.
- OCR sometimes misses substantial text.
- Users need to correct images and reprocess them.
- Active OCR selection needs a more visible border.

**Constraints:**
- Personal use; keep hosting and dependencies inexpensive.
- Do not migrate to serverless before measuring the bottleneck.
- Preserve originals and existing usable results.
- Do not assume particular PaddleOCR features or configuration names are available.
- Avoid introducing a large telemetry platform for the MVP.

---

## 2. Instructions to the implementing LLM

Before coding:

1. Inspect the repository.
2. Locate the relevant files and functions.
3. Identify installed dependency versions.
4. Explain the proposed changes using actual repository paths.
5. Identify unknowns that affect implementation.
6. Implement incrementally, with tests.
7. Do not replace the existing architecture unnecessarily.

Locate:

- Upload endpoints.
- TaskIQ broker, task definitions, and worker initialization.
- PaddleOCR model initialization and inference.
- Image storage and metadata persistence.
- OCR-result schemas and grouping logic.
- Image viewer and overlay-coordinate mapping.
- Selection and translation-panel state.

Record:

- PaddleOCR and PaddlePaddle versions.
- Model names.
- Worker process count.
- Simultaneous OCR-task count.
- Whether models load once per process or once per task.
- Existing preprocessing and retry behavior.

**Initial deliverable:** a concise implementation map and unresolved questions.

---

## 3. Traceability

### 3.1 Goal

For any page and processing attempt, answer:

> What happened, which settings ran, where did time go, and why did it fail?

### 3.2 Identifiers

Use the following identifiers:

| Identifier | Meaning |
|---|---|
| `request_id` | Individual HTTP request |
| `page_id` | Uploaded page |
| `job_id` | Processing attempt |
| `revision` | Committed image/transformation revision |

Requirements:

1. Pass `page_id`, `job_id`, and `revision` explicitly to background tasks.
2. Preserve processing-attempt history.
3. Reprocessing unchanged input creates a new job, not a new image revision.
4. Increment the revision when committed image transformations change.

### 3.3 Structured logging

Use JSON logs.

Example:

```json
{
  "event": "stage_finished",
  "page_id": "example-page",
  "job_id": "example-job",
  "revision": 2,
  "stage": "ocr",
  "duration_ms": 18420,
  "status": "succeeded"
}
```

Measure separately:

1. Upload and storage.
2. Queue wait.
3. Image decoding and EXIF normalization.
4. Orientation detection.
5. Image transformations.
6. Model initialization, when it occurs.
7. OCR detection and recognition separately if the API exposes them; otherwise combined OCR.
8. Reading-order reconstruction and block grouping.
9. Translation.
10. Result persistence.
11. Total processing time.

Use:
- UTC timestamps for events.
- Monotonic clocks for execution durations.
- Enqueue/start timestamps for queue wait; document clock-synchronization assumptions if workers later move to another machine.

### 3.4 Processing metadata

Persist per job:

- Input file size and dimensions.
- Processed dimensions passed to OCR.
- Transformation parameters and order.
- OCR versions, model names, and effective settings.
- Worker process ID.
- Whether model initialization occurred.
- Detected-box count.
- Translation backend, request count, cache hits, and duration.
- Retry attempt.
- Failed stage and sanitized error.

Collect host-level:

- CPU utilization.
- Available RAM.
- Worker-process memory.
- Swap usage.

**Caution:** shared-process resource measurements are not precise per-job attribution when tasks overlap.

### 3.5 UI diagnostics

Add a collapsible **Processing details** panel:

```text
Status: Completed
Queue: 0.4 s
Preprocessing: 1.2 s
OCR: 18.4 s
Translation: 6.1 s
Total: 26.1 s
Revision: 2
Job ID: ...
```

Display failed stages and actionable retry messages.

### 3.6 Safeguards

- Never log credentials, cookies, authorization headers, signed URLs, or image bytes.
- Do not log complete OCR/translation text by default.
- Authorize access to diagnostics.
- Bound log and job-history retention.
- Avoid page/job IDs as metric labels; they create high cardinality.
- Bound retries and prevent duplicate side effects.
- Detect jobs left running after worker failure.
- Do not swallow exceptions or report success before results are persisted.

### Acceptance criteria

- A failed job can be reconstructed using its `job_id`.
- Queue wait, preprocessing, OCR, and translation durations are distinguishable.
- Failures identify their stage.
- Logs do not expose sensitive content or credentials.

---

## 4. Image preservation and transformation model

### 4.1 Source-of-truth rules

1. Preserve the original upload.
2. Create an EXIF-normalized base image.
3. Derive revised images from that base plus saved transformations.
4. Avoid repeatedly rotating or recompressing the previous derivative.
5. OCR coordinates must reference the exact image revision used for inference.
6. The viewer must display that same processed image when showing its OCR overlays.

Suggested conceptual metadata:

```json
{
  "revision": 2,
  "orientation_rotation_degrees": 90,
  "fine_rotation_degrees": -1.5,
  "perspective_corners": null,
  "dewarp_enabled": false,
  "processed_width": 1800,
  "processed_height": 2400
}
```

Adapt this schema to the existing project.

### 4.2 Transformation order

Define one canonical transformation order and use it consistently.

Suggested order:

```text
Original
  → EXIF normalization
  → coarse orientation rotation
  → optional perspective correction
  → fine rotation / deskew
  → optional validated dewarping
  → OCR
```

Corner coordinates must reference a documented intermediate image space.

The frontend preview and backend processing must use equivalent transformation semantics. A server-rendered preview is acceptable if matching transformations in the browser becomes unreliable.

### 4.3 Safety limits

Enforce:

- Upload-size limits.
- Supported image formats.
- Maximum decoded pixel count.
- Maximum transformed output dimensions.
- Temporary-storage limits.

Reject invalid or oversized input with a clear error rather than exhausting server memory.

---

## 5. Correction controls before and after processing

### 5.1 Reusable component

Use the same image-correction component in two places.

#### Before processing

After upload:

1. Show the image preview.
2. Make correction controls available but optional.
3. Provide a prominent **Process** button.
4. If the preview is acceptable, the user can process immediately.
5. Do not require a correction dialog or an additional confirmation when no edits are needed.

#### After processing

In the page viewer:

1. Open correction controls for the existing page.
2. Preview adjustments without running OCR.
3. Offer **Apply and reprocess**.
4. Preserve the previous usable result until replacement succeeds.

### 5.2 Rotation controls

Provide:

- **−90°** preset.
- **+90°** preset.
- **180°** preset.
- **−1° / +1°** fine-adjustment buttons.
- Slider and numeric input with **0.1° precision**.
- Current-angle display.
- **Reset corrections**.
- **Cancel edits**.

The fine step sizes are proposed defaults; keep them configurable.

Define:
- Positive angles as clockwise in the UI.
- Conversion to the backend library’s angle convention.
- Presets as relative adjustments, not unexpectedly replacing the user’s fine angle.
- How displayed angles are normalized.

### 5.3 Rotation behavior

1. Update the preview immediately.
2. Do not run OCR for each slider movement.
3. Commit transformations only on **Process** or **Apply and reprocess**.
4. Generate the authoritative image on the backend.
5. Expand output bounds so rotated content is not clipped.
6. Use a documented background color for newly exposed corners.
7. Increment the revision only when committed transformations change.
8. Never display old OCR polygons over a newly rotated image as though they remain valid.

**Reset corrections:** restore the EXIF-normalized base and clear manual/accepted correction parameters.

**Cancel edits:** restore the last committed revision.

Use appropriate resampling for fine rotations. Avoid unnecessary interpolation for exact right-angle rotations where supported.

### Acceptance criteria

- Presets and fine adjustment work before and after processing.
- An untouched upload can proceed directly to processing.
- Rotation does not clip page content.
- Cancel and reset have distinct, predictable behavior.
- Repeated edits do not cause cumulative image degradation.
- OCR overlays remain aligned with their image revision.

---

## 6. EXIF and automatic orientation

### 6.1 EXIF normalization

1. Decode the uploaded image safely.
2. Apply EXIF orientation, for example with Pillow’s `ImageOps.exif_transpose`.
3. Save a normalized derivative without stale orientation metadata.
4. Generate the preview from the normalized image.
5. Do not reapply EXIF rotation on subsequent processing attempts.

### 6.2 Automatic orientation

1. Check whether the installed PaddleOCR pipeline supports document orientation classification.
2. Add support behind a feature flag.
3. Run it after EXIF normalization.
4. Record prediction and score only if the model returns them.
5. Initially offer a suggested correction instead of silently applying uncertain predictions.
6. Allow the user to ignore the suggestion and process immediately.
7. Store accepted automatic corrections so they are not reapplied on retries.
8. Manual correction must override automatic suggestions.

Distinguish:

- Whole-page orientation.
- Slight page skew.
- Text-line orientation.
- Legitimate vertical Japanese.

### Acceptance criteria

Test:

- Upright images.
- 90°, 180°, and 270° rotations.
- Slightly tilted pages.
- Vertical Japanese.
- Images already corrected through EXIF.

No sample should receive repeated rotation merely because it is reprocessed.

---

## 7. Perspective correction and curved pages

### 7.1 Manual perspective correction

Implement manual correction before automatic corner detection.

1. Add **Adjust page corners** mode.
2. Make it available before and after processing.
3. Display four draggable corners.
4. Validate:
   - Corner ordering.
   - No self-intersection.
   - Minimum area.
   - Coordinates within allowed bounds.
   - Output-size limits.
5. Apply a perspective transform.
6. Preview before committing.
7. Persist corners in the documented coordinate space.
8. Reprocess the committed corrected image.

### 7.2 Automatic corner suggestions

Optional later enhancement:

1. Detect likely page boundaries.
2. Present editable corner suggestions.
3. Do not silently crop uncertain detections.
4. Preserve a manual fallback.

### 7.3 Dewarping

A perspective transform corrects a flat page photographed at an angle. It does not fully flatten a page curved near the spine.

Treat dewarping as experimental:

1. Inspect installed PaddleOCR document-unwarping support.
2. Compare enabled/disabled results on representative pages.
3. Measure additional time and memory.
4. Inspect distortion of text, furigana, equations, and diagrams.
5. Keep originals.
6. Leave disabled by default until validated.

---

## 8. Reprocessing jobs

### 8.1 Suggested API

Adapt to the existing project:

```text
POST /pages/{page_id}/process
GET /jobs/{job_id}
```

Example request:

```json
{
  "revision": 2,
  "preset": "default",
  "force_ocr": true
}
```

### 8.2 Job lifecycle

1. Authorize access to the page.
2. Validate revision and processing preset.
3. Prevent accidental double submissions with idempotency handling.
4. Create a processing attempt.
5. Enqueue the task.
6. Return `202 Accepted` with `job_id`.
7. Display queued/running/succeeded/failed states.
8. Persist results before marking success.
9. Publish the replacement atomically.

### 8.3 Preserve usable results

- Keep prior results visible during reprocessing.
- Clearly identify the revision being displayed.
- Show that a replacement is in progress.
- A failed replacement must not erase the previous usable result.
- An older job finishing late must not overwrite a newer requested result.
- A revision change must invalidate incompatible OCR results and selection state.

### 8.4 Translation caching

Cache by:

- Exact source text.
- Source and target language.
- Translation backend and relevant configuration/version.

Do not translate unchanged text unnecessarily.

### Acceptance criteria

- Double-clicking reprocess does not create unintended duplicate work.
- Failed jobs preserve previous results.
- Late completion cannot overwrite newer results.
- Every result identifies its page, revision, job, and settings.

---

## 9. Missed-text diagnostics and recovery

### 9.1 Diagnose before tuning

Add an authorized debug view containing:

- Exact processed image passed to OCR.
- Raw detected polygons.
- Recognition text and confidence where available.
- Grouped text.
- Final displayed polygons.

Classify the failure:

| Finding | Area to investigate |
|---|---|
| Raw detection misses text | Input quality, detector, resolution |
| Detection exists but recognition is empty | Recognition or filtering |
| Text disappears during grouping | Postprocessing |
| Raw results are correct but boxes are misplaced | Coordinate transforms or viewer scaling |

Do not lower thresholds or increase resolution without confirming the relevant failure.

### 9.2 Reprocessing options

Provide:

- **Reprocess default**.
- **Enhanced detection**, only after validating supported settings.
- **Select region → OCR region**.

Bound enhanced-processing memory and resolution for the 4 GB server.

### 9.3 Region OCR

1. Let the user draw a rectangular region.
2. Convert viewer coordinates to processed-image coordinates.
3. Validate the region.
4. Crop and run OCR.
5. Map polygons back to full-image coordinates.
6. Preserve page/revision association.
7. Avoid silently duplicating existing blocks.
8. Define whether region results replace intersecting blocks or are added with explicit review.

### Acceptance criteria

- Region OCR aligns with the full-image overlay.
- Coordinate conversion works after zoom and resize.
- Region results cannot be applied to an incompatible revision.
- Missing text can be investigated without guessing at model settings.

---

## 10. Active selection styling

1. Centralize selection in `active_block_id`.
2. Provide distinct styles:

| State | Appearance |
|---|---|
| Default | Thin border |
| Hover | Thicker border |
| Active | High-contrast border and subtle fill |
| Keyboard focus | Visible focus indicator |

3. Highlight the corresponding translation block.
4. Clear invalid selection when changing pages or result revisions.
5. Use color plus thickness/fill, not color alone.
6. Provide appropriate keyboard and accessibility semantics.
7. Keep styling from changing box geometry.
8. Verify alignment during zoom, resizing, and image corrections.

### Acceptance criteria

- One active block at a time.
- Matching translation is highlighted.
- Active selection is visibly different from hover.
- Selection styling does not move or resize overlays.

---

## 11. Performance decisions after instrumentation

Measure representative pages before changing infrastructure.

Investigate:

1. Model initialization per task.
2. Model duplication across worker processes.
3. Simultaneous OCR jobs.
4. CPU thread oversubscription.
5. Image resolution.
6. Swap or memory pressure.
7. Translation request count and latency.
8. Queue wait.

Possible improvements must follow evidence:

| Evidence | Candidate change |
|---|---|
| Model loads repeatedly | Reuse initialized models within a supported worker lifecycle |
| RAM exhausted by multiple models | Reduce OCR processes/concurrency |
| Translation dominates | Cache, group requests appropriately, or show OCR first |
| CPU oversubscribed | Tune inference threads and task concurrency |
| Cold first request only | Separate startup cost from steady-state processing |

Make results available progressively where practical:

```text
Original image available
  → OCR text available
  → Translation available
```

Consider serverless only after estimating:

- Actual pages processed per month.
- Warm and cold execution time.
- Model startup cost.
- Required RAM/CPU.
- Persistent storage and queue costs.
- Whether existing server costs would actually decrease.

---

## 12. Implementation order

1. Repository inspection and implementation map.
2. Traceability and raw-overlay diagnostics.
3. EXIF normalization.
4. Reusable pre/post correction UI with preset and fine rotation.
5. Revision-aware reprocessing with idempotency and race protection.
6. Active-selection styling.
7. Region OCR.
8. Manual perspective correction.
9. Automatic orientation and dewarping experiments.
10. Infrastructure decisions using measurements.

---

## 13. Definition of done

The implementing LLM must provide:

- Changed files and rationale.
- Any new dependencies and why they are necessary.
- Database/schema migration details, if applicable.
- Configuration defaults.
- Automated tests and results.
- Manual verification instructions.
- Known limitations.
- No unsupported claims about OCR accuracy or performance.

At minimum, test:

- EXIF normalization.
- Preset and arbitrary-angle rotation.
- No clipping or repeated destructive resampling.
- Pre-processing skip path.
- Post-processing correction and retry.
- Revision/result alignment.
- Duplicate submission prevention.
- Late-job race protection.
- Previous-result preservation after failure.
- Overlay scaling and region-coordinate mapping.
- Selection highlighting.
- Diagnostic logging without sensitive data.

---

## 14. Sources and uncertainty

**Classification:** this document is an engineering proposal, not a benchmark.

The sample image suggests perspective distortion, curvature, and fragmented OCR coverage. It does not establish whether missing text is caused by detection, recognition, grouping, or overlay rendering.

PaddleOCR features and parameter names are version-dependent. Verify against installed versions before implementation.

References:

- PaddleOCR: https://www.paddleocr.ai/
- Pillow EXIF normalization: https://pillow.readthedocs.io/en/stable/reference/ImageOps.html#PIL.ImageOps.exif_transpose
- Pillow rotation: https://pillow.readthedocs.io/en/stable/reference/Image.html#PIL.Image.Image.rotate
- OpenCV geometric transformations: https://docs.opencv.org/4.x/da/d6e/tutorial_py_geometric_transformations.html
- OpenTelemetry concepts: https://opentelemetry.io/docs/concepts/
