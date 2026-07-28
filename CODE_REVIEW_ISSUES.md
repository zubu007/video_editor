# Code Review — Potential Issues

Audit of the uncommitted changes (~2,600 changed lines + new caption/edits/render modules).
Date: 2026-07-26. All 222 tests pass (6 skipped) at time of review.

The scary paths are all handled correctly: no LLM code-exec, no shell injection in
ffmpeg/manim (argv lists, not `shell=True`), no ASS injection, DB access is thread-safe,
and the caption remap math mirrors the renderer's cut/timeline semantics. The real issues
cluster in three areas: **unsanitized client filenames** on the upload endpoints,
**resource leaks** in the persistent render worker, and **render-polling lifecycle bugs**
in the frontend.

Both high-priority items have since been fixed. The remaining sections are tracked as
GitHub issues #1–#20.

---

## High priority — both fixed

### 1. Unsanitized client filenames on the stateless upload endpoints — ✅ FIXED
**`backend/app.py`** — the six `video: UploadFile` endpoints

The stateless upload endpoints joined the client-supplied `video.filename` directly onto
`UPLOAD_DIR`, and the cut-filler-words endpoint additionally derived its `OUTPUT_DIR`
result name and `Content-Disposition` header from it. A name that was not a plain filename
could therefore place a write outside the intended directory, and the `finally` cleanup
could unlink a file outside it. Same-name concurrent uploads also collided.

**Fixed:** `temp_upload_path()` stores every upload under a generated UUID name, carrying
over only a whitelisted extension; `safe_download_name()` reduces any client-supplied name
used for output paths or headers to a single sanitized segment. Both are applied at all six
endpoints. Covered by `backend/tests/test_upload_paths.py`.

### 2. Render polling never stopped on "New video" / project switch — ✅ FIXED
**`frontend/src/App.jsx`** — `resetProjectState`, `resetProjectStateForLoad` (GitHub #1)

Neither reset called `stopRenderPolling()` or reset `isRendering` / `renderProgress`. If a
user started a render then loaded a different project, the old interval kept polling the
stale `jobId`: the Render button stayed stuck on "Rendering…", and when the old job
finished it injected the previous project's result/log into the new project.

**Fixed:** both reset functions now call `stopRenderPolling()` and reset `isRendering` /
`renderProgress` before tearing down the outgoing project's state.

---

## Medium priority

### 3. Resource leaks in the persistent render worker
**`backend/features/video_cutter/cut.py`** — `render_with_edits` (~335),
`render_timeline` (~465), `_load_diagram_overlays` (~368)

The source `VideoFileClip`, the concatenated `final_clip`, and all overlay clips are never
`.close()`d. Each opens an ffmpeg subprocess + file descriptor. This used to be a one-shot
CLI; it now runs repeatedly inside a long-lived server worker, so every render leaks
handles → eventual FD exhaustion / zombie ffmpeg processes.

**Fix:** `try/finally` to close `video`, `final_clip`, and every overlay clip after
`write_videofile`.

### 4. Orphaned `precaption_` intermediate on caption-burn failure
**`backend/app.py`** — `_burn_project_captions` (~1597), `render_target` (~1811)

The full-size intermediate is only deleted on the success path. If `add_captions`/ffmpeg
raises (or "No caption words to render"), the job errors and the large file is left in
`OUTPUT_DIR` forever, accumulating across failed renders.

**Fix:** delete `render_target` in a `finally`/`except`.

### 5. Multi-caption projects drop all but the first caption edit
**`backend/app.py:1572`**

`words` / `style` / `max_words_per_line` come only from `captions_edits[0]`, but `spans`
is built from all caption edits. A second captions region renders no captions. Since
`SUPPORTED_EDIT_TYPES` allows multiple, this is a silent correctness gap.

**Fix:** iterate all caption edits, or enforce one-per-project at save time and reject the
second.

### 6. A single transient poll failure kills render tracking
**`frontend/src/App.jsx:1328`**

The poll `catch` calls `stopRenderPolling()` + `toolError('Lost contact…')` on *any*
thrown error, including one network blip. The backend keeps rendering to completion, but
the UI permanently reports failure and never shows the result.

**Fix:** tolerate N consecutive failures before giving up.

### 7. `-c:a copy` in the caption burn can hard-fail
**`backend/features/captions/burn.py:94`**

Stream-copying audio assumes AAC-in-MP4. The internal pipeline emits AAC so it's fine
today, but the exported `add_captions` API fails on any other audio codec/container.

**Fix:** `-c:a aac`, or fall back to re-encode on copy failure.

### 8. Caption `words` payload unvalidated at save time
**`backend/app.py`** — `validate_captions_metadata` (~1122)

Only `style` is validated. Malformed `words` (e.g. missing `start`/`end`) passes save
(200) then fails deep in the background worker with a `KeyError` after a full encode.

**Fix:** validate word-entry shape (`start`/`end`/`word` presence + type) at save.

### 9. `applyLoadedEdits` clobbers unsaved caption-style selection
**`frontend/src/App.jsx:178`**

Every edit reload overwrites `captionStyleName` / `captionWordsPerLine` from saved
metadata, so previewing an unsaved style then doing any unrelated edit silently reverts
the selection.

**Fix:** seed only when there's no current selection (e.g.
`setCaptionStyleName((cur) => cur ?? saved.style)`).

---

## Low priority / hardening

- **`/api/renders/{filename}`** (`app.py:2106`) and similar joins are unsanitized;
  Starlette blocks `/` in a non-`:path` param so it's not currently exploitable, but add a
  `Path(filename).name` guard for defense-in-depth.
- **`save_upload_file`** (`app.py:801`) reads the whole upload into memory
  (`await upload_file.read()`) — large videos can OOM the server. Stream in chunks.
- **`merge_nearby_pauses`** (`audio_pause/detect.py:251`) uses `current["end"] =
  pause["end"]`, which shrinks a segment if a nested pause is passed. Not triggered by the
  current sorted input, but latent for a public util — use
  `current["end"] = max(current["end"], pause["end"])`.
- **Async `setInterval` poll can overlap/stack** (`App.jsx:1305`) and the interval can be
  created after unmount cleanup (root component, so low impact). Prefer a self-scheduling
  `setTimeout` loop.
- **Progress stalls at 90%** during the caption burn (`app.py:1818`), then jumps to 100% —
  cosmetic; optionally emit a coarse mid-burn tick.
- **`_escape_text`** (`ass_builder.py:54`) doesn't strip `\r`/control chars — very low risk
  from transcripts.
- **`manim_scenes.py`** parses the spec twice (once at import ~87, once in `construct()`
  ~199) — redundant read, and a malformed spec surfaces at import time. Load once and cache.

---

## Test-coverage gaps (informational)

`backend/tests/test_captions.py` covers happy paths but not the risky ones:
- ASS escaping with brace/backslash/newline inside a word.
- `group_words([])`, zero/negative-duration words, page overflow with degenerate timing.
- `burn_captions` non-zero ffmpeg exit (the `RuntimeError` path).
- `remap_words` when everything is cut (empty intervals).
- Integration tests only assert "some bright pixels exist," so a silent font fallback
  (Fontname no longer matching a bundled family) would pass undetected.

---

## Verified correct (skeptical pass — not bugs)

- Job registry thread-safety: all `_JOBS` access under `_LOCK`.
- Worker DB binding: fresh `Session(bind)` from `session.get_bind()`, engine created with
  `check_same_thread=False`; worker only issues `select`s.
- `_run_render_job` error handling: broad `except` sets `status="error"`; per-edit
  stock/diagram failures individually caught.
- Caption remap math mirrors `interval_minus_cuts` / `render_timeline` exactly; no negative
  durations, correct empty-remap fallback.
- Manim path: no `eval`/`exec` of LLM output (labels become inert `Text()`), argv
  subprocess, temp-dir cleanup, `background` validated against `^#[0-9a-fA-F]{6}$`.
- `captionPages.js` mirrors backend `layout.py` grouping exactly (break conditions,
  defaults, linger logic, sentence-end set); empty input handled.
