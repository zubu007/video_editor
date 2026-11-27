# GTA Shorts Studio — Design and Implementation Plan

> **For agentic workers:** Implement this document task-by-task using `superpowers:executing-plans`, or `superpowers:subagent-driven-development` if the user selects delegated execution. Track the checkboxes and validate each phase before continuing. This file is the self-contained product design and implementation handoff; the original chat is not required.

**Goal:** Extend this video editor into a reliable workflow for making original, narrated GTA VI Shorts from permissioned streamer recordings, including generated voiceovers through the user's Voice Studio project.

**Architecture:** Keep the existing React/Vite frontend, FastAPI backend, SQLModel/SQLite storage, Whisper transcription, and FFmpeg/MoviePy processing. Add a persisted Shorts composition model, a shared composition renderer, durable local jobs, and a replaceable speech-provider adapter. Keep Voice Studio in its own environment/process rather than importing its model dependencies into the editor.

**Tech stack:** Python 3.11+, FastAPI, Pydantic, SQLModel/SQLite, FFmpeg, faster-whisper, React 19/Vite. Use existing dependencies where possible. Add frontend tests only with a documented test runner setup.

**Spec:** This document, sections 1–12. Implementation tasks are in section 13.

**Date/status:** 2026-11-16. Requested design handoff, not an assertion that features have been built. Proposed defaults below are implementation decisions, not previously confirmed user preferences.

## Global constraints

- Follow repository `AGENTS.md` typing, naming, docstring, logging, and testing conventions. Existing code has outgrown its podcast-only description: inspect current code rather than assuming `main.py` is the only entry point.
- Preserve existing standard and Dota gaming projects, their render paths, and project-file imports. Add a separate `shorts` project mode.
- Preserve unrelated work: the checkout contained many modified files during design. Record `git status` before implementation; never reset them or commit unrelated changes.
- Local single-user operation is the target. Do not introduce public hosting, multi-user accounts, Redis, or a mandatory cloud service.
- Generated narration is optional. Manual audio import and silent/non-narrated editing must work without Voice Studio, network access, or an LLM key.
- Export requires explicit user action. The app must not publish videos automatically or claim that a video is legally cleared, monetizable, viral, or profitable.
- External provider credentials remain server-side and are excluded from logs, project archives, and client persistence.
- Keep source recordings immutable. Proxies, transcripts, generated audio, and outputs are derived assets.

## Review focus

1. Cuts, repeated source segments, and reordered segments: every visual, voiceover, and caption stays on the correct output time.
2. Restart during speech generation: recover the existing provider request where supported; never silently submit a duplicate generation.
3. Long or irregular footage: rotation, variable frame rate, missing audio, and multi-hour sources preserve sync and manageable resource use.
4. Older projects and missing external assets: migration is non-destructive and missing files are relinkable.
5. Changes after approval: a changed script, voice, source, crop, or mix invalidates the affected preview and final approval.

## 1. Product and editorial intent

The user wants a YouTube channel featuring GTA VI streamer moments. The primary format is a short original story or explanation, not a pipeline that merely reposts a streamer with subtitles. Support three editable briefs: `explained_moment`, `discovery`, and `funny_story`. These are creative starting points, not formulas for guaranteed performance.

Typical workflow:

1. Create a Shorts project and import permissioned footage.
2. Record source/creator details and permission evidence.
3. Select a moment manually or review suggested moments.
4. Assemble setup, event, reaction, and explanation into a composition.
5. Arrange gameplay and optional facecam in a vertical canvas.
6. Write original narration; record/import it or generate it through Voice Studio.
7. Adjust narration timing, source audio, captions, and emphasis.
8. Preview the composed result, review provenance and content, then approve that revision.
9. Export MP4, captions, attribution text, and metadata for manual upload in YouTube Studio.
10. Record results and production costs to compare formats.

### Approaches considered

- **Recommended: extend the editor with a Shorts workspace.** Reuses transcription, captions, media handling, and persistence; requires careful regression coverage.
- **Separate Shorts application.** Cleaner initial isolation but duplicates editing and project infrastructure; reject for this scope.
- **Fully automated clipping and publishing bot.** Faster publishing in theory, but weak editorial control and costly failure modes; explicitly outside this design.

### Delivery boundaries

- **Pilot release:** tasks 0–7 and 10 below. A person can make and export a narrated Short end-to-end.
- **Full handoff scope:** all tasks 0–10, including reviewed suggestions and manual/CSV performance tracking.
- **Deferred:** live stream capture, Twitch/Kick direct URL integrations, automatic face tracking, source separation, automatic YouTube publishing/OAuth/scheduling, YouTube Analytics API sync, multi-user operation, and automatic licensed-music recognition. Do not quietly add these to the critical path.
- No GTA VI-specific HUD detector is required. The existing Dota detector remains Dota-only.

## 2. Verified starting point and limitations

| Existing area | Reuse | Required change |
|---|---|---|
| `backend/features/youtube/download.py` | YouTube VOD download and validation | Range import and configurable long-VOD handling; currently live sources and >3h VODs are rejected |
| `backend/features/gaming/highlight_jobs.py` | Background clip encoding and caption remapping | New Shorts export must render composition edits rather than only trim the source and burn captions |
| `backend/features/gaming/reel_crop.py` | FFmpeg crop/composite techniques | Do not reuse its Dota-specific square geometry for GTA |
| `backend/features/video_cutter/cut.py` | Existing timeline/render primitives | Shared time mapping and supported visual operations for Shorts |
| `backend/features/captions/` | Caption styles, ASS generation, burning | Output-time narration captions and safe-area layout |
| `backend/features/face_detection/detect.py` | Optional initial face-region suggestion | Never assume largest detected face is the correct streamer; manual crop remains authoritative |
| `backend/features/llm/provider.py` | Existing configurable text-model client | Structured script/candidate suggestions with validation |
| `backend/storage/database.py` | SQLite models and migration entry point | Shorts entities, schema versioning, and durable jobs |
| `backend/features/project_io/` | `.vedit` export/import and relinking | New composition/audio/provenance references and backward compatibility |
| `frontend/src/App.jsx`, `frontend/src/services/api.js` | App navigation and API conventions | Small dedicated Shorts panels, not another large block of logic in App |

The assessment attempted focused tests but `.venv/bin/pytest` could not start: the Python interpreter failed to locate its standard library (`ModuleNotFoundError: encodings`). Establish a functioning environment and baseline before treating existing code as verified. Do not interpret this as a test failure in the application itself.

## 3. Persisted model and time semantics

Use typed Pydantic payloads, SQLModel records, UUID identifiers, UTC timestamps, and a schema version on stored composition JSON. Avoid storing unvalidated arbitrary dictionaries as the public contract.

### Entities

- **SourceRecord:** `id`, `project_id`, `media_asset_id`, platform, source URL, original title, creator name/channel URL, original VOD duration, imported start offset, asset fingerprint, and creation time.
- **RightsRecord:** source ID, status (`unknown`, `permission_recorded`, `owned`, `restricted`), evidence text or local attachment reference, commercial-use note, required attribution, optional expiry, and revenue-share note. Evidence records what the user supplied; it is not a legal determination. Track game/music considerations separately from streamer permission.
- **ShortComposition:** `id`, `project_id`, title, editorial format, immutable revision number, schema version, output settings, and validated composition snapshot. Each mutation creates a new revision; an export/job pins one revision.
- **Composition payload:** ordered `segments`, `layout`, `narration_blocks`, `audio_edits`, `caption_tracks`, `text_overlays`, `review_flags`, and optional publication metadata. Define nested models in `shorts/schema.py`.
- **SourceSegment:** stable ID, source/media ID, `source_in`, `source_out`; selected segments concatenate in list order at speed 1.0. Source times are relative to the imported asset, not the original VOD. Original VOD time = asset time + imported start offset.
- **NarrationBlock:** stable ID, text, language, optional voice ID/provider settings, generated/imported audio-asset ID, output start, optional slot duration, trim-in/out, gain, revision, and generation input hash. With no slot duration, the available slot ends at the composition end; never infer a slot from the next spoken block.
- **AudioAsset:** managed path, checksum, format, channels, sample rate, measured duration, provider/model/voice provenance where available, script hash, and optional word alignment. Keep the original and a normalized PCM derivative.
- **Job:** type, status, project/composition/revision IDs, validated payload, deduplication key, stage/progress, attempt count, provider job ID, worker lease/heartbeat, result references, error code/message, and timestamps.
- **ExportRecord:** pinned composition revision/hash, export settings, output assets/checksums, review snapshot, elapsed render time, and actual/unknown cost entries.
- **PerformanceRecord:** export ID, YouTube video ID/URL, publication time, measurement window, format, raw views, engaged views, stayed-to-watch percentage, average percentage viewed, subscribers gained, actual revenue/currency, and production minutes. Missing values remain null rather than zero.

### Timing contract

- All intervals are half-open `[start, end)` in seconds. Validate finite values, `0 <= start < end <= media_duration` for source ranges.
- Derive each segment's output interval cumulatively. Never use source timestamps as narration or overlay output timestamps.
- Narration, manual text, crop keyframes, and audio duck/mute intervals use **output time**. Imported source subtitles are mapped through each selected segment, including repeated segments.
- Source word selection uses midpoint inclusion, then clamps/remaps boundaries, matching existing caption conventions. Narration word times come from audio alignment, not estimates based on character count.
- Support cuts, reordered/repeated segments, static crops, keyframed crop centers, text, and zooms in the first release. No speed ramps, crossfades, or arbitrary transitions in this scope.
- Source range and order changes keep output-time narration positions unchanged, mark the composition for review, and flag overflow; do not guess the user's intended retiming.
- A selected legacy project may be converted only for supported edit types. Unsupported enabled edits produce a named warning and require manual resolution; never silently omit them from an export.
- Async generation never mutates a pinned revision. On completion, store the audio asset, then transactionally inspect the current composition: if the stable block ID still exists and its generation input hash matches, create a new composition revision attaching the audio while preserving other current edits. Otherwise retain the asset as an unattached result and offer manual attachment. Either attachment invalidates render/review, but a stale result must never overwrite current text, settings, or media.

## 4. Import and long-VOD workflow

- Accept local MP4/MOV/MKV sources and permitted YouTube VOD URLs; normalize/probe using existing safe media handling.
- Add optional `start_seconds`/`end_seconds` range import. Validate against probed duration; retain original URL and offset. Attempt provider-supported section download, but do not promise it avoids downloading the full source for every format.
- Keep the existing three-hour default for full URL downloads; add an explicit per-import override after presenting estimated size when known. Default requested range cap: 30 minutes. Larger ranges require the same explicit override.
- For long local footage, generate a 720p proxy and lazy thumbnails; transcribe selected ranges first. Process audio in 10-minute chunks with 2-second overlap and timestamp-based overlap deduplication; allow cancellation between chunks.
- Never upload an entire VOD to an LLM. Text suggestions consume only selected transcript windows. Visual analysis is optional and off by default.
- Default combined managed-media budget: 50 GiB, configurable. Estimate required work space where possible, stop with an actionable disk-space message, and never auto-delete source or referenced narration files.
- Show source availability, import progress, proxy/transcription status, cancellation, retry, and relinking in the UI.
- No bypass of access controls or DRM. Direct live capture is not part of this work.

## 5. Vertical layout and consistent rendering

### Layout editor

- Default output: 1080×1920, H.264, `yuv420p`, AAC 48 kHz, MP4 with faststart. Default 30 fps; allow 60 fps. Both are constant-frame-rate exports.
- Provide `gameplay_full`, `facecam_top`, and `facecam_bottom` templates. Facecam template default: 30% of canvas height for facecam and 70% for gameplay, with user-adjustable split.
- Each visual region has a normalized source rectangle and normalized output rectangle. Validate bounds and minimum size; quantize encoding coordinates to even pixels.
- Store layout overrides by **segment ID**, not only source ID: repeated appearances of the same source may use different crops. Gameplay and facecam both sample that segment's current source frame; independent facecam files and picture-in-picture from another simultaneous source are deferred. A project-level template supplies defaults, while each segment owns its region rectangles and crop/zoom keyframes. Keyframe times are output-relative and must lie inside the owning segment's derived output interval; changes to segment order/duration mark invalid keyframes for explicit correction rather than silently moving them.
- Manual draggable crops with aspect lock and reset; optionally propose a face region using existing detection. Source crop coordinates refer to rotation-corrected frames.
- Offer fit-with-background and fill-with-crop. Background defaults to solid black; blurred background is optional, not a prerequisite.
- Display editable safe-area guides. Initial design guides: 8% left, 15% right, 8% top, 20% bottom. These are conservative product defaults, not official fixed YouTube UI dimensions.
- Keyframed crop centers interpolate linearly; crop dimensions stay fixed within a segment. Clamp to frame bounds. Use the same geometry calculation in preview and export.

### Render contract

`build_render_manifest(composition: ShortCompositionSnapshot, assets: AssetCatalog) -> RenderManifest`

The manifest resolves segment ordering, source/output time mapping, crops, zooms, overlays, caption tracks, audio timing, asset hashes, and output settings. `render_short(manifest: RenderManifest, output_path: Path, progress: ProgressCallback) -> RenderResult` is the sole final Shorts render path.

Generate a low-resolution proxy render from the same manifest for authoritative playback. Interactive browser layout previews are approximate; final approval is based on a rendered proxy tied to the current revision. Cached previews must invalidate on any manifest-affecting change.

Render order: normalize each source's orientation/timebase → trim each segment → compose its gameplay/facecam/crops into the normalized output canvas → concatenate normalized segment canvases → output-time overlays → mix source/narration audio → burn captions → validate output. Resolve output-relative crop/zoom keys into segment-local time during manifest construction. Do not concatenate heterogeneous raw frames before applying their source-specific geometry. Preserve original frame timing until explicit CFR conversion. A/V drift acceptance: no more than one output frame at fixture checkpoints.

Existing quick Dota highlight export stays compatible. The new Shorts action must not route through its trim-only implementation.

## 6. Voiceover creation and Voice Studio integration

### Confirmed repository and integration decision

The user confirmed [debpalash/VoiceStudio](https://github.com/debpalash/VoiceStudio). Source inspected on 2026-11-16 at commit **`6fe6f4dd62b477ab5fbf4d94500e3c0298d05232`**. This is a source-inspected baseline, not a deployment tested by this editor. Record the actual deployed version/model revision during implementation and compare its schema before using a different release.

**Use the existing HTTP API directly from the editor backend.** No CLI wrapper, new bridge, library import, upstream fork, or additional paid cloud service is needed for the baseline. Keep VoiceStudio separately installed and use manual audio import if the service is unavailable. The exact installed instance/base URL, selected model, voice, and any credentials still need configuration; the repository identity is no longer blocked.

Verified sources at the inspected commit:

- [Speech API implementation and schemas](https://github.com/debpalash/VoiceStudio/blob/6fe6f4dd62b477ab5fbf4d94500e3c0298d05232/backend/api/routers/openai_compat.py)
- [Engine discovery](https://github.com/debpalash/VoiceStudio/blob/6fe6f4dd62b477ab5fbf4d94500e3c0298d05232/backend/api/routers/engines.py)
- [Authentication](https://github.com/debpalash/VoiceStudio/blob/6fe6f4dd62b477ab5fbf4d94500e3c0298d05232/docs/api-auth.md)
- [Private service deployment](https://github.com/debpalash/VoiceStudio/blob/6fe6f4dd62b477ab5fbf4d94500e3c0298d05232/docs/production-private-api.md)
- [Application and model license notice](https://github.com/debpalash/VoiceStudio/blob/6fe6f4dd62b477ab5fbf4d94500e3c0298d05232/LICENSE-NOTICE.md)

### Actual VoiceStudio HTTP contract

Base URL defaults to `http://127.0.0.1:3900` (server root, without `/v1`). Use a dedicated HTTP client in the adapter; this is separate from the editor's text-LLM client/settings.

| Upstream route | Adapter use |
|---|---|
| `GET /health` | Check service reachability; this alone does not prove a model is ready |
| `GET /engines` | Inspect TTS inventory, availability, active selection, and execution-device metadata |
| `GET /v1/models` | Discover advertised model/engine IDs; aliases are also present, so listing is not proof of installed weights |
| `GET /v1/audio/voices` | Returns `{voices, engines}`; voice entries have `voice_id`, `id`, `name`, `type`, and optional language metadata |
| `POST /v1/audio/speech` | JSON request; completed audio bytes in the HTTP response, not a durable job ID or audio URL |

Map editor requests explicitly:

```json
{
  "model": "<verified-selected-engine-id>",
  "input": "Your original narration text.",
  "voice": "<selected-profile-id-or-verified-engine-preset>",
  "response_format": "wav",
  "speed": 1.0,
  "language": "en"
}
```

The angle-bracket values are configuration placeholders, not valid literal defaults. Enforce nonblank text and the upstream **4096-character maximum** per block. The schema accepts speed 0.25–4.0; expose 1.0 by default and retain the actual measured duration. Omit `stream_format` for the initial WAV implementation. Successful output is binary `audio/wav`; probe it and resample locally to the editor's 48 kHz PCM derivative rather than assuming the engine's native sample rate.

Use stable profile IDs rather than profile names. Duplicate names return 409. Entries with `type=openai_alias` (for example `alloy`) all map to an engine default; do not display them as distinct real voices. Prefer profile entries in the picker; an engine default/preset may be selected only with its actual identity explained. OpenAI-style model aliases also route to active engines: use a verified explicit engine and record resolved model metadata. The inspected code special-cases `omnivoice` through active-engine routing, so verify its resolution rather than treating even that spelling as a guaranteed weight identity.

Optional `seed`, `instructions`/`instruct`, `duration`, `num_step`, and `guidance_scale` exist in the schema but are engine-dependent. Keep advanced controls disabled until validated against the chosen engine. Duration is a target, not a guarantee; engine availability is not commercial clearance.

For this selected endpoint, advertise adapter capabilities **async provider jobs=false, cancellation=false, word timestamps=false, idempotency=false**. `submit()` runs in the editor's worker and returns a succeeded `SpeechSubmission` only after complete validated audio is materialized. `poll()` is unsupported; `cancel()` returns false. The editor still provides its own asynchronous job ID to its frontend. Closing the HTTP connection is not proof remote computation stopped. Do not call nonexistent upstream job-status/cancel endpoints or assume an idempotency header will prevent regeneration. A timeout or restart after submission follows the interrupted/unknown-outcome rules below. Local input-hash caching prevents known duplicate submissions, not uncertain upstream duplicates.

The API does not return TTS word alignment: generate captions using the editor's existing transcription/alignment fallback. Do not confuse VoiceStudio's transcription endpoints or speech-discovery document with a TTS job API.

Parse upstream errors from `error.message/type/param/code`, retaining sanitized `detail` when present. Test 400 invalid/unavailable engine, 401 authentication, 403 model-license/access refusal, 409 ambiguous voice, 429 capacity, 503 load/readiness, and transport timeout. Honor `Retry-After` only for explicit pre-generation refusal that is known safe to retry; do not automatically retry ambiguous generation failures. Preserve `X-OmniVoice-Routing` and `X-OmniVoice-Routing-Reason` in diagnostics and surface degraded routing.

### Deployment and model selection

- Existing native desktop backend is the preferred local connection on Apple Silicon; upstream documents macOS 13.3+ and MPS support. Do not assume every engine works on every device or install CUDA on macOS.
- For a separate server, use an exact tested Docker release tag/digest with persistent data/model volumes, following upstream private-service documentation. Do not assume the documentation's example release contains every feature inspected on main. Avoid rolling tags for a verified deployment.
- Loopback access is unauthenticated by upstream design. Remote access uses `Authorization: Bearer <key>` configured through upstream `OMNIVOICE_API_KEY`; store the matching editor secret as `VOICE_STUDIO_API_KEY`. The key grants broad server privileges, so keep the instance private. Remote credentials require HTTPS or the documented secure private deployment; do not pass them to the browser. If a share PIN is also enabled, it is an independent gate—prefer the documented private-service setup with share PIN disabled rather than silently bypassing it.
- Configure `VOICEOVER_PROVIDER=voice_studio`, `VOICE_STUDIO_BASE_URL`, optional `VOICE_STUDIO_API_KEY`, and required selected `VOICE_STUDIO_MODEL`. Voice ID is saved per narration block; use a 600-second configurable generation deadline and a separate short connection timeout. There is no CLI transport setting in this implementation.
- Install/approve the chosen model in VoiceStudio's own interface first and warm it with a short request. Its model-load budget may exceed the editor's generation deadline; do not trigger unattended multi-GB downloads as part of an export. `/health` passing is insufficient for generation readiness.
- The upstream notice identifies the app as AGPL-3.0-only and explicitly distinguishes model/voice/output terms. It identifies default `k2-fsa/OmniVoice` pretrained weights as **CC-BY-NC**. Do not auto-select those weights for this commercial channel, and do not infer commercial permission from the app being free or an engine being installed. Record exact selected weights/revision, relevant terms, voice authorization, and the user's evidence of commercial-use rights. Unknown status remains unknown; retain manual narration as the fallback while a suitable model is chosen.
- This design does not establish commercial clearance for any alternative model, and a license acknowledgement checkbox does not grant rights. Do not copy upstream code into this repository or claim process separation automatically settles software-license obligations.

Full completion still requires a live smoke test against the configured instance and selected voice/model; source inspection and fake-provider tests are not that test.

### Editor-owned speech protocol (proposed, not Voice Studio's API)

Define in `backend/features/voiceover/schema.py` and `provider.py`:

```python
class SpeechProvider(Protocol):
    def capabilities(self) -> SpeechCapabilities: ...
    def list_voices(self) -> list[VoiceDescriptor]: ...
    def submit(self, request: SpeechRequest) -> SpeechSubmission: ...
    def poll(self, provider_job_id: str) -> SpeechResult: ...
    def cancel(self, provider_job_id: str) -> bool: ...
```

- `SpeechCapabilities`: supported languages/formats/settings, max text length when known, and flags for async jobs, cancellation, word timestamps, and idempotency. Unsupported controls are disabled in the UI.
- `VoiceDescriptor`: provider voice ID, display name, languages, and any available model/license metadata. Unknown licensing must be labeled unknown; do not infer permission from the voice's presence in a list.
- `SpeechRequest`: text, language, voice ID, validated provider-specific settings, desired WAV output, application idempotency key. Model/version are explicit where provider supports them.
- `SpeechSubmission`: status (`queued`, `running`, `succeeded`), optional provider job ID, optional immediate `SpeechResult`. A synchronous provider may complete during submit in a background worker.
- `SpeechResult`: status (`queued`, `running`, `succeeded`, `failed`, `cancelled`), artifact locator when successful, optional word timestamps, actual provider metadata, and structured error. Adapter materializes the artifact into managed storage; never expose provider URLs/secrets directly to the frontend.
- Validate returned audio by decoding/probing; reject corrupt, empty, over-limit, or unexpected content. Default narration block limit: 2 minutes and downloaded artifact limit: 100 MiB; expose clear errors.
- Normalize to PCM WAV at 48 kHz for editing, retain the source file, measure actual duration, and cache by script + language + voice + model/version + settings + provider identity hash. Do not treat a cache hit as a new paid request.
- Use provider alignment when valid; otherwise transcribe/align generated audio with existing Whisper tooling and allow manual correction. Preserve actual spoken text when it differs from the script.
- API credentials live in server environment/config. Use the HTTP settings and concrete endpoint mapping above; retain `VOICEOVER_PROVIDER=disabled` for the manual-audio workflow.
- Default one active generation job; use a shared heavy-work slot with transcription/rendering on the same machine to avoid GPU/RAM contention. Allow a separate slot when the provider runs remotely.
- On connection loss after submit, query the known provider job or use verified idempotency. Without either, set the local job to `interrupted` with `error_code=provider_outcome_unknown` and offer explicit retry; never automatically regenerate uncertain requests. An acknowledged retry creates a new attempt linked to the interrupted job and warns that the earlier request may still finish or have incurred cost.
- Before external submission, durably record the attempt's idempotency key and `submission_state=submitting`; persist the provider job/result identifier immediately on response. Restart recovery of a `submitting` attempt without a persisted response uses the same unknown-outcome rule, covering a crash between provider acceptance and local persistence. Submission state belongs to the durable job attempt, not an in-memory flag.
- Cancellation may only stop local waiting if the provider cannot cancel. State that accurately and discard late results for cancelled revisions; track any actual cost if available.
- Use only voices the user is authorized to use. Default to a narrator voice, not imitation of the clipped streamer. Generation alone does not establish original editorial value.

### Narration editor

- Editable script blocks with optional hook/context/payoff labels; no mandatory AI script generation.
- Generate one block, regenerate selected blocks, preview the voice, and import WAV/MP3/M4A narration.
- Show text, selected voice, status, waveform, actual duration, output start, trim, gain, and stale-generation indication.
- Script or voice changes invalidate generation; layout-only changes invalidate render, not speech.
- If audio exceeds its slot or the composition, offer moving it, editing/regenerating text, trimming, or extending the composition. Do not silently cut off words or time-stretch by default.
- Optional script suggestions use the existing LLM provider with transcript/source context. Label unsupported factual claims for review; never fabricate GTA mechanics or streamer quotations.

## 7. Audio, captions, and review

- Separate source and narration buses. Default gains: source 0 dB, narration 0 dB; default source ducking while narration plays: −12 dB, with 100 ms attack and 250 ms release, editable/off.
- Overlapping narration blocks are flagged and require correction or explicit overlap acceptance before approval. Missing source audio produces silence without failing the render.
- Manual output-time mute/bleep intervals; apply the same changes to caption text when desired, while preserving original transcript separately.
- Optional final two-pass loudness normalization targets −14 LUFS integrated and ≤−1 dBTP true peak. These are project defaults, not claims of mandatory YouTube values. Handle silent/very short audio without treating undefined loudness as a crash.
- Default caption style: maximum two lines, up to four words per phrase; preserve manual line breaks and allow overriding phrase boundaries. Keep narration and streamer transcript as separate editable tracks.
- Let the user choose narration-only, source-only, both, or no captions. When both overlap, use separate safe-area rows; show collision warnings with facecam/text and permit manual adjustment.
- Export corrected SRT as well as optional burned-in captions. All exported subtitle times are output-relative.
- Review panel records source attribution, permission notes, possible music, graphic/sexual content, language, spoilers, and unsupported factual claims. These are manual review flags, not a fake automated copyright detector.
- Draft preview is always allowed. Final export requires review acknowledgement for the pinned revision. Unresolved rights flags require an explicit recorded acknowledgement; do not present this as legal clearance.

## 8. Durable jobs and storage

- SQLite-backed job states: `queued → running → succeeded|failed|cancelled|interrupted`; include `cancel_requested` as a flag. Workers claim jobs transactionally with a lease; use a 5-second heartbeat and 30-second stale-lease threshold.
- Start with one local worker and bounded queues. Long jobs run outside request handlers. Polling returns stable job IDs and human-readable stage/error details.
- On restart, recover stale jobs: reattach provider jobs when possible; otherwise mark interrupted and offer retry. Local encode retries restart encoding from an immutable manifest, not from partial output.
- Deduplicate by job type, composition revision/input hash, and settings. Repeated clicks return the active job rather than duplicate work.
- Write artifacts to job-specific temporary files and atomically rename only after validation. Failures leave no completed-looking MP4.
- Cleanup removes unreferenced temporary files/proxies only. Imported source, referenced narration, exported files, and permission evidence require explicit deletion. Show disk usage before deleting anything.
- All media paths resolve through managed asset IDs and approved relinking. Do not execute commands or read arbitrary paths from an imported project file. Validate remote artifact origins and redirects against configured provider locations, with byte/time limits.
- If a batch is cancelled, stop queued children and request cancellation of running children; completed exports remain available.

## 9. Suggested API and frontend organization

These are new **editor-owned** routes, not claims about existing endpoints or Voice Studio routes. All mutations validate project ownership in this local app's data model and enforce revision conflicts with HTTP 409.

| Route | Purpose |
|---|---|
| `POST /api/projects/{id}/shorts` | Create composition from selected source ranges |
| `GET /api/shorts/{id}` | Read current composition and revision |
| `PUT /api/shorts/{id}` | Replace validated composition with `expected_revision` |
| `POST /api/projects/{id}/source-imports` | Start VOD/range import job |
| `PUT /api/sources/{id}/rights` | Save source permission/attribution record |
| `GET /api/voiceover/capabilities` | Connection state, verified capabilities, unavailable reasons |
| `GET /api/voiceover/voices` | Voice choices from configured provider |
| `POST /api/shorts/{id}/narration/{block_id}/generate` | Start generation pinned to block/input hash |
| `POST /api/shorts/{id}/narration/{block_id}/audio` | Import and validate manual audio |
| `POST /api/shorts/{id}/preview` | Render current immutable revision proxy |
| `POST /api/shorts/{id}/review` | Save acknowledgement for a specific preview/revision hash |
| `POST /api/shorts/{id}/exports` | Validate review and create final export job |
| `POST /api/projects/{id}/shorts/batch-exports` | Export individually approved compositions |
| `GET /api/jobs/{id}` / `POST /api/jobs/{id}/cancel` | Durable status and cancellation |
| `POST /api/projects/{id}/moment-suggestions` | Analyse selected source window; return job ID |
| `GET /api/projects/{id}/moment-suggestions` | Read saved candidates and evidence |
| `POST /api/exports/{id}/performance` | Save manual/CSV-derived measured results |

Job starts return HTTP 202 and `{job_id, status_url}`. Invalid ranges/settings return 422 with field errors; unavailable provider returns 503 with a user-actionable reason. Asset/result downloads use the application's controlled file-serving mechanism.

Frontend workspace: Sources → Moments → Layout → Narration → Captions & Audio → Review & Export → Results. Tabs preserve unsaved-edit warnings and never discard pending script edits during polling. Add keyboard-accessible crop controls alongside dragging, clear loading/error/empty states, and accessible labels.

### File map

- `backend/features/shorts/{schema.py,timing.py,composition.py,layout.py,render.py,routes.py}`: validated compositions, mapping, geometry, manifest/rendering, and API.
- `backend/features/voiceover/{schema.py,provider.py,voice_studio.py,service.py,routes.py}`: provider protocol, real adapter, audio materialization/cache, and API.
- `backend/features/audio/mix.py`: source/narration mixing, fades, mute/bleep, loudness.
- `backend/features/jobs/{models.py,service.py,worker.py,routes.py}`: durable queue and lifecycle.
- `backend/features/sources/{schema.py,service.py,routes.py}`: provenance, rights, and import orchestration over existing downloader.
- `backend/features/moments/{schema.py,suggest.py,routes.py}`: bounded, evidence-backed suggestions.
- `backend/features/performance/{schema.py,service.py,routes.py}`: results and cost tracking.
- `backend/storage/database.py` and a new `backend/storage/migrations.py`: model registration and versioned additive migrations.
- `backend/features/project_io/{schema.py,export.py,import_.py}`: versioned persistence and relinking.
- `backend/app.py`: register new routers and lifecycle services; avoid unrelated route rewrites.
- `frontend/src/components/Shorts/`: `ShortsWorkspace.jsx`, `SourcesPanel.jsx`, `MomentsPanel.jsx`, `LayoutPanel.jsx`, `NarrationPanel.jsx`, `AudioPanel.jsx`, `ReviewExportPanel.jsx`, `ResultsPanel.jsx`, and colocated styles.
- `frontend/src/services/shortsApi.js`: typed-by-documentation request/response wrappers using the shared API client; expose that client without duplicating its base URL/error handling.
- `frontend/src/hooks/useShortsProject.js`: revision-aware fetching/saving and job polling.
- `docs/VOICE_STUDIO_INTEGRATION.md`: verified upstream commit/contract, setup, troubleshooting, and license notes.
- `docs/SHORTS_WORKFLOW.md`: user guide, operational limits, recovery and manual upload instructions.

## 10. Moment suggestions and performance measurement

### Suggestions

- Manual clip selection ships first and remains available without AI.
- Candidate fields: source ID, source-relative start/end, suggested title, format, transcript evidence spans, rationale, component scores, and review state.
- Analyse only a user-selected range. Use transcript context and local audio-energy/laughter-like peaks as candidate signals; label inferred emotion as a heuristic. Do not label loudness a guaranteed highlight.
- LLM refines candidate boundaries and explains its recommendation from supplied evidence. Validate JSON, enforce range bounds, and drop unsupported evidence/quotes. Do not let model output execute tools or become filenames.
- Default candidate length 15–60 seconds; user may edit. Merge overlapping duplicates, rank by explainable criteria (setup/payoff/context clarity), and present up to 10 candidates per request.
- GTA-specific visual event models and chat-spike ingestion are deferred. Leave an interface for future signals but do not ship unimplemented controls.

### Results and costs

- Manual form plus CSV import with a documented app-owned column template; do not assume arbitrary YouTube Studio CSVs share that schema. Provide mapping/validation errors and downloadable template.
- Keep qualified/engaged views separate from raw public views. Record the observation window so 24-hour results are not silently compared to 7-day results.
- Show format-level median metrics and per-clip production time; avoid a single opaque “viral score.”
- Costs: manual hourly labor rate × minutes/60 + actual or manually entered tool/provider costs + actual rights payments/revenue shares. Record estimates separately from actuals, with currency. Unknown costs stay unknown.
- Show profit only from known actual revenue and costs; display incomplete-data status otherwise. Scenario calculations must be clearly labeled assumptions, not predictions.
- Initial experiment suggestion: 20–30 clips over two weeks across the three formats. This is a configurable workflow suggestion, not a publishing quota or algorithm requirement.

## 11. Project files and compatibility

- Introduce `.vedit` schema version 2 when the new data lands, retaining a version-1 reader and migration path. Export version 2 for Shorts projects; test old projects opening without changed behavior.
- Persist compositions/revisions, source offsets, source/rights records, narration scripts/settings, audio fingerprints/references, review/export metadata, and performance records.
- Never export API keys, cookies, tokens, absolute provider credentials, or worker leases. Local managed paths must pass current path validation on import.
- Missing voice files can be relinked by fingerprint; changing a fingerprint invalidates associated approval and render caches. Speech regeneration is explicit, not triggered merely by reopening a project.
- Existing project files reference external assets; preserve that model and include an asset manifest with instructions. A self-contained media ZIP is deferred; do not imply `.vedit` embeds audio/video.

## 12. Verification and release acceptance

Use deterministic synthetic media for automated tests. Do not require real GTA footage, remote LLMs, Voice Studio, or paid services in the default suite. Test the actual Voice Studio adapter separately using the user's approved instance and a short neutral script.

- Geometry fixtures: 16:9, ultrawide, portrait, rotated video, and facecam regions at each corner.
- Timing fixture: three reordered segments, one repeated segment, a word crossing a cut, narration at a segment boundary, and a late source event. Check source/output mapping and A/V sync.
- Audio fixtures: silent video, stereo source with mono narration, overlapping narration, overlong narration, corrupt provider output, and bleep/caption consistency.
- Job fixtures: restart mid-encode, lease expiry, cancellation, full disk, duplicate clicks, provider timeout after accepting work, and late results for stale revisions.
- Import fixtures: >3h URL rejection by default, explicit override, selected range offset, chunk overlap deduplication, missing source, and unsafe path/URL rejection.
- Persistence fixtures: version-1 project load, version-2 roundtrip, missing audio relink, secrets exclusion, and changed asset fingerprint invalidation.
- UI checks: keyboard crop editing, stale-preview badge, provider unavailable/manual-import fallback, revision conflict, overflow warning, and complete review/export flow.
- Real export inspection: use FFprobe to verify 1080×1920, configured CFR, H.264/AAC, duration, and playable output; listen to the narration/reaction transitions and inspect frames for caption/HUD collisions.
- Re-run existing captions, highlights, reel crop, project IO/resume, frame-rate, portrait, and video-cutter tests. Run the full backend suite and frontend lint/build before completion; report pre-existing failures separately with evidence.
- Record environment, test commands/results, upstream integration commit, one sample export, and any remaining limits in the completion report. Passing mocks do not establish real speech integration or production throughput.

## 13. Implementation tasks

Within each task: add the named behavior tests first, confirm meaningful failures, implement, run the focused tests, then review the diff. Commit only task-owned changes if commits are requested. Do not skip prerequisites or stop after producing a scaffold.

### Task 0 — Establish baseline and verify Voice Studio identity

**Files:** existing environment/config; create `docs/VOICE_STUDIO_INTEGRATION.md`.
**Produces:** working test environment; recorded upstream repository/commit and supported interface, or explicit integration blocker.

- [ ] Record current changes, inspect current tests and dependency lock, and repair/recreate the local Python environment without changing unrelated code or upgrading all dependencies.
- [ ] Run `pytest`, `ruff check .`, `black --check .`; in `frontend`, run `npm run lint` and `npm run build`. Record pre-existing failures, missing prerequisites, and actual baseline.
- [ ] Use confirmed repository `https://github.com/debpalash/VoiceStudio` and the inspected commit in section 6. Configure the actual instance/base URL, selected engine/model revision, voice, hardware, and credentials; compare installed schema against the source-inspected baseline.
- [ ] Document actual request/response examples with secrets removed, tested revision, launch/health/warm-up procedure, and commercial model/voice terms. If the instance is unavailable, continue independent tasks but leave its live integration test explicitly blocked.

### Task 1 — Persist composition, sources, and project-file compatibility

**Files:** `shorts/schema.py`, `shorts/composition.py`, `sources/schema.py`, `sources/service.py`, storage models/migrations, project IO modules.
**Tests:** `backend/tests/test_shorts_schema.py`, `test_shorts_project_io.py`.
**Interfaces:** `save_composition(project_id: str, snapshot: ShortCompositionSnapshot, expected_revision: int) -> ShortCompositionSnapshot`; `get_composition(composition_id: str) -> ShortCompositionSnapshot`.

- [ ] Test invalid/out-of-bounds/non-finite ranges, revision conflicts, immutable saved snapshots, source offsets, and missing references.
- [ ] Test additive migration and version-1 compatibility, version-2 roundtrip, relinking, secret exclusion, and fingerprint-based invalidation.
- [ ] Implement entities and transaction-safe revision storage; validate references stay within the project.
- [ ] Implement versioned file import/export and media relinking for the new records.
- [ ] Run `pytest backend/tests/test_shorts_schema.py backend/tests/test_shorts_project_io.py backend/tests/test_project_resume.py -q`.

### Task 2 — Durable jobs and bounded worker

**Files:** `jobs/` modules, `backend/app.py` lifecycle registration.
**Tests:** `backend/tests/test_durable_jobs.py`.
**Interfaces:** `enqueue_job(kind: str, payload: dict, input_hash: str) -> JobRecord`; `cancel_job(job_id: str) -> JobRecord`; typed payload validation is dispatched by job kind.

- [ ] Test transactional claim/deduplication, 30-second stale leases, restart reconciliation, cancellation, late completion, and artifact finalization.
- [ ] Implement one bounded worker, heartbeat, stable polling, stage progress, cleanup, and job-specific temp storage.
- [ ] Add a heavy-work concurrency slot shared by new transcription/render/voiceover jobs; register existing heavy operations where they can overlap with Shorts work.
- [ ] Run `pytest backend/tests/test_durable_jobs.py -q`; restart the service during a synthetic long-running job and verify recoverable status.

### Task 3 — Range imports, proxies, and provenance UI

**Files:** `sources/` routes/service, existing YouTube downloader and transcript services, `SourcesPanel.jsx`, `shortsApi.js`.
**Tests:** `backend/tests/test_source_ranges.py`, `test_transcript_chunks.py`.
**Interfaces:** `import_source(request: SourceImportRequest) -> JobRecord`; source job result yields `SourceRecord` and managed asset IDs.

- [ ] Test long-VOD limits/override, interval validation, original-time offsets, transcript chunk deduplication, cancellation, missing audio, and disk budget errors.
- [ ] Implement range fetching, proxy generation, selected-window transcription, relinking, and immutable source records.
- [ ] Add source/rights forms and durable job progress to the UI.
- [ ] Run `pytest backend/tests/test_source_ranges.py backend/tests/test_transcript_chunks.py backend/tests/test_youtube_download.py -q`.

### Task 4 — Shared timing, vertical layout, and manifest renderer

**Files:** `shorts/{timing.py,layout.py,render.py}`, existing cutter helpers as needed, `LayoutPanel.jsx`.
**Tests:** `backend/tests/test_shorts_timing.py`, `test_shorts_layout.py`, `test_shorts_render.py`.
**Interfaces:** `map_source_interval(segment: SourceSegment, output_start: float, start: float, end: float) -> tuple[float, float] | None`; manifest/render interfaces from section 5.

- [ ] Test reordered/repeated segments, crossing captions, rotated coordinates, even crop dimensions, 30/60 fps, and no-audio sources.
- [ ] Implement output mapping, three templates, manual crop controls, crop keyframes, and safe-area guides.
- [ ] Implement shared proxy/final rendering with revision hash and cache invalidation; reject unsupported enabled legacy effects by name.
- [ ] Run `pytest backend/tests/test_shorts_timing.py backend/tests/test_shorts_layout.py backend/tests/test_shorts_render.py backend/tests/test_portrait_render.py backend/tests/test_frame_rate.py -q`.
- [ ] Inspect a synthetic vertical output and compare its timing/geometry against the manifest and browser controls.

### Task 5 — Narration assets and real Voice Studio adapter

**Files:** `voiceover/` modules, `NarrationPanel.jsx`, settings UI, `.env.example`, integration documentation.
**Tests:** `backend/tests/test_voiceover_provider.py`, `test_voiceover_service.py`, opt-in `test_voice_studio_integration.py`.
**Interfaces:** speech protocol in section 6; `generate_narration(composition_id: str, block_id: str, expected_revision: int) -> JobRecord`; `import_narration(...) -> AudioAsset` with validated project/block IDs and uploaded file input.

- [ ] Implement deterministic fake-provider tests covering sync/async success, unsupported capabilities, invalid output, timeout-after-submit, caching, cancellation, and outdated block results. Include an unrelated layout edit during generation (attach to a new current revision without losing it), a changed script (leave result unattached), and a deleted block (never recreate it).
- [ ] Implement manual audio import, probe/normalization, measured duration, waveform, playback, block placement, and regeneration invalidation.
- [ ] Map the section-6 HTTP contract to `VoiceStudioProvider`: JSON speech request → binary WAV response; profile ID selection; engine discovery; no provider polling/cancellation/idempotency; no automatic uncertain retries. Add contract tests for 4096-character validation, voice aliases, routing metadata, malformed audio, license refusal, and bounded capacity backoff.
- [ ] Add backend-only connection settings and capabilities/voice discovery; keep manual import available when disconnected.
- [ ] Run `pytest backend/tests/test_voiceover_provider.py backend/tests/test_voiceover_service.py -q`.
- [ ] Run opt-in generation against the user's real instance, listen to the resulting short narration, verify duration/metadata, and record the upstream commit plus selected weights/revision. An unavailable instance or unselected suitable model is an explicit incomplete item, not permission to substitute an unrelated service.

### Task 6 — Mix audio and remap captions

**Files:** `audio/mix.py`, `shorts/render.py`, existing captions helpers, `AudioPanel.jsx`, narration/caption UI.
**Tests:** `backend/tests/test_shorts_audio.py`, `test_shorts_captions.py`.
**Interfaces:** `build_audio_mix(manifest: RenderManifest) -> AudioMixPlan`; `build_caption_tracks(manifest: RenderManifest) -> list[CaptionTrack]`.

- [ ] Test −12 dB ducking and configured fades, overlap/overflow warnings, silence, output clipping, audio alignment fallback, and repeated source-word remapping.
- [ ] Implement narration/source buses, manual gains, mute/bleep intervals, optional two-pass loudness normalization, and peak checks.
- [ ] Implement independent narration/source caption tracks, collision guides, corrections, and SRT output.
- [ ] Run `pytest backend/tests/test_shorts_audio.py backend/tests/test_shorts_captions.py backend/tests/test_captions.py -q`; listen to a source/reaction/narration transition fixture.

### Task 7 — Review, export package, and complete pilot UI

**Files:** `shorts/routes.py`, render/export services, `ShortsWorkspace.jsx`, `ReviewExportPanel.jsx`, app/API wiring.
**Tests:** `backend/tests/test_shorts_export.py`; frontend tests under `frontend/src/components/Shorts/__tests__/`.
**Produces:** MP4 + SRT + attribution text + metadata JSON + traceable export record.

- [ ] Test that review is tied to a successful preview of the current revision; stale revisions/assets block final export until re-reviewed.
- [ ] Implement review acknowledgements, export defaults, batch queue, per-item failures, cancellation, and downloadable package files.
- [ ] Add title/description/attribution fields and editable editorial format; do not upload to YouTube.
- [ ] Add Vitest/React Testing Library only as needed for meaningful frontend behavior tests; define `npm run test` and test unsaved edits, stale preview, revision conflicts, keyboard crop controls, and unavailable-provider fallback.
- [ ] Run `pytest backend/tests/test_shorts_export.py -q`, frontend tests, lint, and build. Perform the full manual-import → edit → narrate → review → export workflow.

### Task 8 — Reviewed moment and script suggestions

**Files:** `moments/` modules, existing LLM client, `MomentsPanel.jsx`, optional script-assist controls in narration panel.
**Tests:** `backend/tests/test_moment_suggestions.py`, `test_narration_suggestions.py`.
**Interfaces:** `suggest_moments(source: SourceRecord, window: TimeRange, transcript: list[Word]) -> list[MomentCandidate]`; `suggest_script(context: ScriptContext) -> ScriptSuggestion`.

- [ ] Test bounded context, malformed model output, unsupported quotations, invalid timestamps, overlap deduplication, and no-provider manual fallback.
- [ ] Implement transcript/audio candidate generation, validated LLM refinement, evidence display, accept/reject/edit actions, and optional original-script suggestions.
- [ ] Run `pytest backend/tests/test_moment_suggestions.py backend/tests/test_narration_suggestions.py -q`; inspect whether suggested boundaries include setup and payoff on a permitted sample.

### Task 9 — Performance and cost tracking

**Files:** `performance/` modules, `ResultsPanel.jsx`.
**Tests:** `backend/tests/test_short_performance.py`.
**Interfaces:** `record_performance(export_id: str, sample: PerformanceInput) -> PerformanceRecord`; `summarize_formats(project_id: str, window: str) -> list[FormatSummary]`.

- [ ] Test null/zero distinction, CSV validation, duplicate imports, mixed currencies, incompatible measurement windows, and incomplete profit data.
- [ ] Implement manual entry, template CSV import/export, format medians, production minutes, actual costs, and clearly labeled hypothetical revenue scenarios.
- [ ] Run `pytest backend/tests/test_short_performance.py -q`; verify one calculation manually against the entered values.

### Task 10 — Regression, documentation, and delivery evidence

**Files:** `docs/SHORTS_WORKFLOW.md`, `docs/VOICE_STUDIO_INTEGRATION.md`, README, relevant tests and configuration.

- [ ] Verify all acceptance cases in section 12, including a restart/recovery drill and version-1 project import.
- [ ] Run full `pytest`, `ruff check .`, `black --check .`, and frontend test/lint/build commands. Separate newly introduced failures from recorded baseline failures; do not claim pass without output.
- [ ] Document setup for local/remote Voice Studio, manual fallback, source rights records, safe-area editing, export packages, storage limits, and failure recovery.
- [ ] Produce one synthetic fixture export and one user-authorized real sample when available. Record source duration, machine/hardware, processing time, peak disk usage, and actual output properties; do not invent throughput targets.
- [ ] Provide a completed task checklist, changed-file summary, verification results, upstream commit, sample output location, and remaining external blockers. Full completion requires the real Voice Studio test; pilot completion may explicitly use manual audio.

## 14. Policy and business context for implementers

The product supports editorial work; it cannot certify copyright permission, YouTube Partner Program approval, or profit. Voiceovers must contribute an original explanation/story, not merely disguise a repost. Permission records and a human review step do not override platform or rights-holder rules.

Use current official sources when implementing platform-specific guidance. Do not hard-code monetization thresholds, release dates, or payout estimates in the editor:

- [YouTube channel monetization policies](https://support.google.com/youtube/answer/1311392)
- [YouTube Partner Program eligibility](https://support.google.com/youtube/answer/72851)
- [YouTube announced program changes](https://support.google.com/youtube/answer/12843009)
- [YouTube advertiser-friendly guidelines](https://support.google.com/youtube/answer/6162278)
- [Rockstar footage policy](https://support.rockstargames.com/articles/7bNaeoMFTV0iUDGhStTXvz/policy-on-posting-copyrighted-rockstar-games-material)
- [YouTube Shorts storytelling discussion](https://blog.youtube/creator-and-artist-stories/youtube-shorts-deep-dive/)
- [YouTube content analytics definitions](https://support.google.com/youtube/answer/12220281)

## 15. Instructions to the implementing Codex session

Read this file and current `AGENTS.md`, inspect the working tree, and implement tasks 0–10 in order. Preserve existing edits and behavior. Make reasonable implementation decisions within this design and record them. Use the confirmed VoiceStudio repository and section-6 HTTP contract; resolve missing instance/access/model details rather than inventing them, while continuing independent tasks. Treat optional/deferred features exactly as scoped. Do not publish videos or incur new paid-service charges without authorization. Do not report full completion until end-to-end composition rendering, real Voice Studio generation, persistence/recovery, and the required tests have been demonstrated; identify any externally blocked tasks precisely.
