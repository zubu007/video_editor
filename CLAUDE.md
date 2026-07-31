# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

An automated podcast video editor: a FastAPI backend that transcribes video (faster-whisper),
detects filler words and silences, generates AI editing plans (Groq Cloud LLMs), pulls B-roll from
Pexels, and renders cut videos (MoviePy/ffmpeg) — plus a React + Vite frontend for an
upload → detect → review → render workflow.

## Commands

Backend (Python 3.11+, managed with `uv`):

```bash
uv pip install -e .                          # install runtime deps from pyproject.toml
uv pip install --group dev                   # install dev deps (pytest, ruff, black)

python run_server.py                         # start API on :8000 with reload
# equivalent: uvicorn backend.app:app --reload --host 0.0.0.0 --port 8000

pytest                                        # run all tests (testpaths = backend/tests)
pytest backend/tests/test_filler_words.py     # single file
pytest backend/tests/test_filler_words.py::test_name   # single test

ruff check . [--fix]                          # lint
black . [--check]                             # format

python backend/main.py /path/to/video.mp4 --model_size base   # legacy CLI entry
```

Frontend (`frontend/`, React 19 + Vite):

```bash
npm run dev        # Vite dev server (:5173)
npm run build      # production build
npm run lint       # eslint
```

The interactive API docs live at `http://localhost:8000/docs` once the server is running.

## Environment

Requires a `.env` file at the repo root:

```
API_KEY=...           # Groq Cloud API key — editing-plan generation
PEXELS_API_KEY=...    # stock footage download

# Optional — only needed for the caption-removal feature (see below):
SUBTITLE_REMOVER_DIR=third_party/VideoSubtitleRemover
SUBTITLE_REMOVER_PYTHON=third_party/VideoSubtitleRemover/.venv/bin/python
```

The frontend reads `VITE_API_BASE_URL` (defaults to `http://localhost:8000`).

### Caption removal (external tool) setup

The caption-removal feature shells out to the third-party
[VideoSubtitleRemover](https://github.com/SysAdminDoc/VideoSubtitleRemover) CLI as an
**isolated subprocess**. That repo ships its own package named `backend` (same name as ours)
and heavy GPU deps, so it is *not* imported — it is cloned with its own virtualenv:

```bash
git clone https://github.com/SysAdminDoc/VideoSubtitleRemover third_party/VideoSubtitleRemover
cd third_party/VideoSubtitleRemover
python -m venv .venv && .venv/bin/pip install -r requirements.txt
# Sanity check (CPU-only):
.venv/bin/python -m backend.processor -i sample.mp4 -o out.mp4 -m sttn --gpu -1
```

`SUBTITLE_REMOVER_DIR` / `SUBTITLE_REMOVER_PYTHON` point our backend at the clone and its
interpreter (defaults shown above). `SUBTITLE_REMOVER_USE_GPU` (default `0`) toggles
`--gpu 0` vs `--gpu -1`; the start endpoint reads it via `use_gpu_from_env()` and a
`?use_gpu=` query param overrides it per request. **Mac caveat:** the repo's `paddlepaddle-gpu`
/ `onnxruntime-directml` deps are NVIDIA/Windows-only; on macOS install the CPU subset and the
tool runs the slow CPU inpainting path. **Windows + NVIDIA GPU** (e.g. RTX 50-series): see the
detailed setup in [README.md](README.md#caption-removal-burned-in-subtitles). If the
directory/interpreter is missing, the feature's endpoints return an error rather than crashing
the server.

## Architecture

### Backend — two parallel API styles

[backend/app.py](backend/app.py) is a single large module holding all routes and Pydantic
models. There are **two coexisting interaction patterns**, and this is the most important thing
to understand:

1. **Stateless, upload-per-call** (`POST` endpoints taking `video: UploadFile`): the client
   uploads a file with every request; the file is saved to `temp/uploads/`, processed, and
   deleted in a `finally` block. Examples: `/api/transcript/segments`,
   `/api/filler-words/detect`, `/api/video/cut-filler-words`, `/api/editing-plan/generate`.

2. **Stateful, project-based** (the newer flow, persisted in SQLite): `POST /api/video/upload`
   stores the file under a UUID `file_id` and creates a `Project` + `MediaAsset`. Subsequent
   work references the `file_id` (e.g. `/api/transcript/words/{file_id}`,
   `/api/audio/pauses/{file_id}`) and edits are saved as `EditOperation` rows via
   `/api/projects/{project_id}/edits/*`. `POST /api/projects/{project_id}/render` collects the
   enabled edits and renders the final video **as a background job** (see Rendering below).
   Uploaded files here are **not** auto-deleted.

The frontend uses pattern #2 end-to-end (see data flow below).

### Feature modules ([backend/features/](backend/features/))

Each subpackage is a self-contained capability; routes in `app.py` orchestrate them. They speak
a common dict shape: time ranges are `{"start", "end"}` and words are `{"start", "end", "word"}`.

- `transcript/extract.py` — `faster-whisper` (CPU, int8). Three granularities: segments,
  sentences (assembled from word timestamps until sentence-ending punctuation), and words.
- `filler_words/detect.py` — regex match against a hardcoded `FILLER_WORDS` list over word-level
  transcript; returns ranges to cut.
- `audio_pause/detect.py` — silence detection (pydub) with `merge_nearby_pauses` to coalesce gaps.
- `video_cutter/cut.py` — `cut_filler_words(video_path, ranges, output_path)` is the **generic
  renderer**: it builds keep-clips between the given cut ranges and concatenates with MoviePy.
  Used both for filler-word removal and for project render. Handles MoviePy 1.x/2.x subclip API.
- `audio/extract.py` — downsampled waveform peaks for frontend visualization.
- `editing_plan/` — `generator.py` → `llm_client.py` (`EditingPlanLLM`) calls Groq Cloud in JSON mode.
  Available effects are declared in `feature_registry.py` (`AVAILABLE_FEATURES`: zoom,
  insert_stock_footage, text_overlay); `get_feature_descriptions_for_llm()` injects them into the
  prompt and the response is validated against the registry (timestamps in bounds, known feature,
  required params present). **To add an editing effect, register it here** so the LLM can emit it.
- `pexels/download.py` — searches Pexels and downloads B-roll into `temp/outputs/`.
- `captions/` — burns shorts-style animated captions (word-by-word highlight/pop) into a video.
  `layout.py` groups word-level transcript entries into 2-5 word "pages"; `styles.py` holds the
  `STYLE_PRESETS` (bold-pop, rainbow, karaoke, minimal) and bundled fonts in `backend/assets/fonts/`;
  `ass_builder.py` emits an ASS subtitle document (one Dialogue event per word for highlight styles);
  `burn.py` runs ffmpeg's libass `ass` filter as a **final pass** over an already-rendered video —
  `add_captions(video_path, words, output_path, style=...)` is the entry point. Word timestamps must
  be on the timeline of the video being burned: `remap.py` (`output_intervals` + `remap_words`)
  converts source-time words to output time, mirroring the renderer's cut/timeline semantics
  exactly. Persisted as `EditOperation` rows of `type="captions"` (see Persistence).
  `text_caption.py` is the **manual** counterpart (the "Notes" tab): hand-written notes placed
  at the playhead that stream on with a typewriter reveal. `build_text_caption_ass` emits a
  growing-prefix sequence of ASS events (same per-word technique, at character granularity) with
  a readable box; `add_text_captions` burns them. Persisted as `type="text_caption"` edits whose
  `details` carry `text`, `position` (top/middle/bottom) and optional `reveal_seconds`, and burned
  as a further ffmpeg pass after the transcript-caption pass in the render worker.
- `caption_removal/` — removes burned-in captions via the external VideoSubtitleRemover tool
  (see Environment → caption-removal setup). `remove.py` builds and runs the tool's CLI as an
  isolated subprocess; `jobs.py` is a thread-safe **in-memory** job registry (jobs are lost on
  restart). Because removal takes minutes, the endpoints are async: `POST
  /api/video/remove-captions/{file_id}` starts a `BackgroundTasks` job and returns a `job_id`;
  `GET /api/caption-removal/status/{job_id}` is polled until `done`, then returns the cleaned
  video's `/api/renders/{filename}` URL. The frontend's `EditorTools/CaptionTool` drives this.
- `gaming/death_detect.py` — Dota 2 death/alive interval detection (for the "Edit a gaming
  video" mode). `detect_death_intervals(video)` → `[{start, end, duration}]` dead ranges, read
  from the HUD, not the scene (Dota does **not** grayscale on death). It colour-matches the
  bottom hero globe to the player's fixed top-bar slot (`identify_player_slot`), then flags the
  golden respawn-box under that slot as the dead signal; `DotaHudLayout` holds the
  1920×1080-calibrated coordinates. `gaming/jobs.py` runs it as a **background job**. Wired to the
  frontend's **"Deaths" tab** (`EditorTools/DeathCutsPanel`, shown only for gaming-mode projects):
  `POST /api/gaming/detect-deaths/{file_id}` → poll `GET /api/gaming/death-detect/status/{job_id}`;
  `GET /api/gaming/slot-preview/{file_id}` returns the auto slot + 5 base64 portrait thumbnails for
  a **manual slot selector** (override the auto-match when it's wrong). Detected ranges save as
  `cut` EditOperations (`source="death_detection"`). Only Radiant slot centres are calibrated; see
  [TODO.md](TODO.md) item 3 for findings and open work (Dire calibration).
- `gaming/reel_crop.py` — reframes a highlight clip as a **square reel** for the "Highlights" tab.
  A centred crop takes the frame to 1:1 (equal bands off each side), which keeps the top hero bar
  and the bottom hero/ability/item panel but discards the minimap and K/D/A readout; both are
  cropped out of the discarded bands, scaled up (1.3x / 2x) and composited back onto the square —
  minimap bottom-left (bottom edge pinned above the ability bar), K/D/A top-left under the hero
  bar. `plan_reel(width, height)` resolves the geometry (`ReelLayout` is calibrated at 1920x1080
  and scales, like `DotaHudLayout`) and `build_reel_filter()` emits it as one ffmpeg
  `-filter_complex` graph, so `highlight_jobs.run_highlight_job(..., square=True)` stays a single
  re-encode pass. Landscape sources only — `plan_reel` raises `ValueError` otherwise and the job
  records it. Driven by `square` on `POST /api/gaming/highlight-clip/{file_id}` (the panel's
  "Crop to square for reels" checkbox, on by default).

### Persistence ([backend/storage/database.py](backend/storage/database.py))

SQLModel over SQLite at `data/video_editor.db` (created on startup via `init_db()` in the app
lifespan). Core tables: `Project`, `MediaAsset` (one source file, keyed by `file_id`), and
`EditOperation` (non-destructive edit, with `enabled` flag and a JSON `details` column). Routes get
a session via the `get_session` FastAPI dependency. The generic edit endpoints accept the types in
`SUPPORTED_EDIT_TYPES` (`cut`, `zoom`, `insert_stock_footage`, `diagram`, `captions`,
`text_caption`). Note the render worker dispatches each type with hardcoded `edit.type == ...`
branches rather than off `SUPPORTED_EDIT_TYPES` — adding a type means both registering it here
*and* adding a render branch, or it silently no-ops at render. Timeline
segments — the ordered, possibly rearranged source ranges built in the frontend's `Timeline`
component — are stored as `EditOperation` rows of `type="timeline_segment"` (order in
`details["position"]`) and are managed only via `GET/PUT /api/projects/{id}/timeline`. When a
project has a saved timeline, render uses `render_timeline()` (segments in saved order, cuts
subtracted and zoom/stock applied within them); otherwise it falls back to `render_with_edits()`
on the original timeline. When the project has an enabled `captions` edit, MoviePy renders to an
intermediate `precaption_*` file and `_burn_project_captions()` runs as a final pass: words come
from the edit's `details["words"]` (else the source is re-transcribed), get filtered to the edit's
span, remapped from source to output time (`captions/remap.py` mirrors the cut/timeline
semantics), and burned onto the final file. Caption `details` also carry `style` (validated
against `STYLE_PRESETS`, listed at `GET /api/captions/styles`) and `max_words_per_line`.

### Rendering (async job + progress)

Rendering can take minutes, so it is **asynchronous**: `POST /api/projects/{id}/render`
validates the project/media/source file, then returns `{job_id, status}` immediately and runs
the work in a `BackgroundTasks` worker. Poll `GET /api/render/status/{job_id}` for
`{status, progress, output_url, filename, applied_edits, error}`; `progress` is a 0.0–1.0
fraction and `output_url` is populated only once `status == "done"`. Failures are recorded on
the job as `status="error"` rather than raised from the start request.

- `video_cutter/jobs.py` is the thread-safe **in-memory** job registry (`create_job` /
  `get_job` / `update_job`), mirroring `youtube/jobs.py`. Jobs are lost on restart.
- The worker itself is `_run_render_job` / `_execute_render` in `app.py` (it needs the route
  layer's edit-resolution helpers). It opens its own `Session` on the engine handed to it as
  `bind` — taken from the request session's `get_bind()`, which keeps tests that swap in an
  in-memory engine via the `get_session` override working transparently.
- Progress comes from MoviePy: `cut.py`'s `_RenderProgressLogger` is a `proglog` logger passed
  as `logger=` to `write_videofile`. It tracks the **video** bar (`frame_index` on MoviePy 2.x,
  `t` on 1.x) and deliberately ignores the audio `chunk` bar, which completes first and would
  otherwise send progress back to zero. `render_with_edits` / `render_timeline` take an
  `on_progress` callback; when captions are enabled the encode is scaled to 0–0.9 to leave room
  for the caption burn pass.
- Frontend: `App.jsx` starts the job and polls every `RENDER_POLL_INTERVAL_MS`, keeping the
  interval id in `renderPollRef` (cleared on done/error/unmount) and driving the
  `.render-progress` bar on the render page.

### Filesystem conventions

- `temp/uploads/` — uploaded source videos, named `{file_id}{ext}`. `find_uploaded_video()`
  probes known `VIDEO_EXTENSIONS` to resolve a `file_id` back to a path.
- `temp/outputs/` — rendered videos and downloaded stock footage.
- `data/` — the SQLite DB.

### Frontend ([frontend/src/](frontend/src/))

React 19 + Vite, no router (view is toggled by `currentView` state in `App.jsx`). All backend
calls go through [frontend/src/services/api.js](frontend/src/services/api.js) (axios). CSS Modules
per component. Main flow in `App.jsx`:

upload → backend returns `file_id`/`project_id`/`media_asset_id` → fetch waveform + word
transcript in parallel → `SilenceTool` detects pauses → user confirms cuts (saved as
`EditOperation`s) → `renderProject` produces the final file. Key components: `VideoPlayer/`
(with `WaveformProgress` overlaying cut markers), `TranscriptPanel/`, `EditorTools/SilenceTool`,
`Upload/VideoUpload`. CORS in `app.py` is allow-listed to the Vite/CRA dev ports.

Burned-in captions UI: the "Captions" side-panel tab hosts `EditorTools/CaptionsPanel` (preset
gallery from `GET /api/captions/styles`, words-per-line, save/toggle/delete of the project's
single `captions` edit — full-video span, transcript words in `metadata.words`). The live
preview is `VideoPlayer/CaptionOverlay`, a CSS approximation of the libass burn driven by
`utils/captionPages.js`, which mirrors the backend's page grouping (`captions/layout.py`) —
keep the two in sync. Note `EditorTools/CaptionTool` is the unrelated caption-*removal* tool.

## Conventions (from AGENTS.md)

- `snake_case` functions/vars, `PascalCase` classes, `UPPER_SNAKE_CASE` constants.
- Type hints on all signatures; `from __future__ import annotations` is used throughout the backend.
- Google-style docstrings.
- Raise specific exceptions; routes translate them to `HTTPException` with appropriate status codes
  (404 for `FileNotFoundError`, 400 for `ValueError`, 500 otherwise).

## Notes / gotchas

- Transcription runs on CPU with `compute_type="int8"`; larger Whisper `model_size` values
  (tiny→large) trade speed for accuracy. The frontend passes `"base"`.
- Several docs (README, AGENTS.md) are partially stale — e.g. AGENTS.md references a top-level
  `main.py` and `requirements.txt`-based install, but the real entry points are `run_server.py`
  / `backend/main.py` and deps live in `pyproject.toml`. Trust the code and this file.
- The repo has many uncommitted changes and planning docs (`*_PLAN.md`, `QUICKSTART*.md`); these
  describe intended/future work and don't all reflect the current code.
