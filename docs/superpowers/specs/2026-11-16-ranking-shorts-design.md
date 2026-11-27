# Ranking Shorts — feature design specification

Date: 2026-11-16
Deliverable: implementation handoff for Codex; no application changes in this task.
Status: requested functionality specified; proposed defaults below remain editable design decisions, not user approvals.

## 1. Purpose and requirements

Add a **Create a ranking short** option to the app's opening screen. It opens a dedicated editor inside the existing app for assembling a portrait compilation such as “Top 5 failed tattoo moments.” The user supplies the heading, video links, playback order, and custom clip names. The app downloads the sources, plays them serially, overlays the heading and ranking list, and exports one finished video.

User requirements:

- A separate editing workspace reachable alongside existing startup options.
- Five source clips for the main use case, supplied as Shorts or Reels links.
- Explicit user control of clip sequence, heading, and each clip's display name.
- Persistent ranking numbers with clip names beside them.
- Confirmed behavior: reveal each clip name when its clip starts; keep revealed names visible afterward.
- Visual styling controls for the heading and ranking titles.
- Download sources and render the complete sequence.

The attached images are visual references, not instructions embedded in a document. `oar2.jpg` shows a dark heading band, outlined text, and a persistent ranking column over the video. `images.jpeg` shows a heading over full-frame footage and bold outlined ranking numbers. Neither requires reproducing its exact text, footage, or central subtitle. The six entries in the first image are reference content; five remains the default.

## 2. Scope and proposed defaults

These decisions make the spec buildable without implying the user selected them:

| Item | V1 decision |
| --- | --- |
| Editor | Dedicated Ranking Shorts workspace within the current React app, not a separate desktop window |
| Number of entries | Start with five; support two through ten using Add clip / Remove clip |
| Playback | Start in rank order 1 → N; allow countdown N → 1 and custom order |
| Ranking column | Always displayed top-to-bottom as 1 → N, independently of playback order |
| Source providers | Public YouTube videos/Shorts and Instagram Reels; other providers deferred |
| Import fallback | Upload a local video into any clip slot |
| Output | Portrait 1080 × 1920, 30 fps, MP4 with H.264 video and AAC audio |
| Cuts | Hard cuts; no transition effects in V1 |
| Audio | Original clip audio, with per-clip mute and volume; silent clips remain silent |
| Clip duration | Full source initially, with user-adjustable trim in/out |
| Default styling | Dark header band, white bold outlined text, yellow active rank |
| Reveal | Names appear at the start of their clips and persist; numbers are present from the first frame |

Out of scope: automatic selection/ranking of clips, AI headings, automatic publishing, voiceover, music search, automatic subtitles, removing source watermarks/captions, and general multitrack editing. No transcription is required to enter or use this editor. Do not add platform login/cookie collection in V1.

## 3. Architecture choice and alternatives

**Recommended design:** a dedicated workspace and ranking composition model, reusing the app's media storage, download utilities, fonts, and background-job conventions. This keeps ranking controls understandable while supporting multiple independent source videos.

Alternatives considered:

1. Add ranking controls to the existing single-source editor. Less new navigation, but the current source-loading, preview, reopening, and rendering assumptions do not represent this composition cleanly.
2. Build a standalone application. Strong separation, but duplicates startup, media handling, saved projects, and export infrastructure unnecessarily.

The recommended approach is the author's proposal; only the name-reveal behavior has been explicitly confirmed separately by the user.

## 4. Existing app integration

Repository inspected on the date above; there are pre-existing uncommitted changes. Preserve them and re-read touched code before implementation.

- `frontend/src/App.jsx`: opening choices, single-source editor state, project resumption. Add the ranking choice and route `project_type === 'ranking'` directly into its own editor before the ordinary source-loading flow.
- `frontend/src/services/api.js`: existing API client; extend with ranking methods.
- `backend/app.py`: FastAPI setup, `PROJECT_TYPES` currently contains `standard` and `gaming`; include `ranking` and mount feature routes.
- `backend/storage/database.py`: SQLite/SQLModel Project and MediaAsset storage. One project can own multiple assets, but current list/open endpoints select only its latest asset. Ranking must not use that latest asset as the entire composition.
- `backend/features/youtube/download.py` and `jobs.py`: existing yt-dlp downloader and in-memory background jobs. Reuse suitable utilities, but implement provider validation and clip-specific attachment. Existing download success must not implicitly open the ordinary editor or create five separate projects.
- `backend/features/video_cutter/cut.py`: current source-oriented rendering and composition helpers. Reuse safe low-level helpers; do not assume `render_timeline` already concatenates independent source assets.
- `backend/features/project_io/`: `.vedit` export/import/relink infrastructure. Extend explicitly for ranking metadata and all referenced sources.
- `backend/assets/fonts/`: bundled Anton, Bangers, and Montserrat ExtraBold; use matching files in preview and export.

Suggested boundaries: `frontend/src/components/RankingShorts/` for workspace, clip list, preview, and style inspector; `backend/features/ranking/` for schemas, routes, composition, rendering, and jobs. Keep feature logic out of the already-large App and backend application modules.

## 5. User flow and workspace

1. Select **Create a ranking short** on the opening screen.
2. Create a saved ranking project immediately, even before downloading any footage.
3. Enter heading and five source URLs; edit each display name. Start downloads individually or use **Download all**.
4. Arrange playback order, assign ranks, trim clips, and adjust framing.
5. Adjust heading and ranking styles while viewing the portrait composition.
6. Preview the whole sequence, then select **Export video** and download the finished MP4.
7. Return later through the existing saved-project list, with a **Ranking** badge.

Desktop layout:

```text
Back to projects | Project name | Saved / Saving / Save failed | Export video
┌────────────────────────┬──────────────────────────┬───────────────────────┐
│ CLIPS / PLAYBACK ORDER  │ PORTRAIT PREVIEW         │ DESIGN                │
│ Download all           │ Heading                  │ Heading text/style    │
│ 1. [rank] name / URL   │ 1. revealed title        │ Ranking text/style    │
│ 2. [rank] name / URL   │ 2. active title          │ Layout preset         │
│ 3. [rank] name / URL   │ 3.                       │ Selected clip framing │
│ 4. [rank] name / URL   │ 4.     active footage    │ Audio / Trim          │
│ 5. [rank] name / URL   │ 5.                       │                       │
│ Add clip              │ Play / Seek / Time       │                       │
└────────────────────────┴──────────────────────────┴───────────────────────┘
                   Sequence strip with clip boundaries and durations
```

Use the app's existing dark UI conventions. At narrow widths, keep preview accessible and move Clips/Design into tabs. Provide keyboard-accessible Move earlier / Move later controls as well as drag-and-drop; show focus and descriptive labels.

Each clip card includes thumbnail, playback position, assigned rank, editable name, URL, download status/progress, retry, replace/upload, trim, mute/volume, and remove. Selecting a card seeks to its start and selects its inspector. Platform metadata may suggest a name only when the name is empty; it must never overwrite user text.

## 6. Rank, order, and time semantics

Give each clip a stable ID. Its `rank` and `playback_order` are distinct fields. Dragging changes playback order only, never the name, rank, source, trim, or framing. Order presets sort playback by assigned rank; the list visibly labels both values.

Ranks must be unique and contiguous 1…N. Changing a rank swaps with the entry that currently owns it. Removing a clip compacts ranks and playback positions; adding a clip appends the next rank. Confirm removal only if necessary to avoid losing unsaved edits, following the app's established behavior.

For clip i in playback order, calculate a trimmed duration `d_i = out_i - in_i`, then quantize to output frames once, using `frames_i = max(1, round(d_i * 30))`. Segment boundaries and total duration derive from cumulative frame counts. Reject trims shorter than one output frame rather than silently manufacturing longer footage. Rendering may hold the final frame for a fractional-frame rounding remainder.

Intervals are half-open `[start_frame, end_frame)`. At a boundary, the next clip becomes active immediately, and its title is revealed on that frame. At the end of playback, hold the last valid output frame in preview. Rank names visible at a time are those whose clips started at or before that time. This must be computed from time, not accumulated UI state: seeking backward hides future names, seeking forward reveals every earlier name, and reordered/countdown playback reveals by sequence rather than numeric rank.

All numbers remain visible throughout. Only the active row is highlighted. Earlier titles remain in normal styling; future titles occupy blank space. Never show metadata names before their reveal. Heading remains visible across all segments.

## 7. Composition and design controls

Use a single canonical 1080 × 1920 coordinate system, scaled uniformly for preview. Layout coordinates, font metrics, wrapping, cropping, and reveal timing must have one shared specification used by preview and rendering.

Two presets:

- **Header band** (default, reference 1): dark background with heading centered in a 220 px top band; footage viewport from y=220 to y=1740, with dark footer below; ranking column overlays footage.
- **Full-frame** (reference 2): footage fills the canvas; heading overlays its top area. Optional translucent heading backing improves contrast.

Initial guides: content left margin 48 px, ranking number column width 112 px, title column width 500 px, ranking area y=320…1500. Distribute N rows evenly within that area, reducing type sizes for larger N. Avoid rightmost 160 px and bottom 240 px for essential text by default. These are adjustable composition guides, not a promise about platform UI placement.

Heading controls: plain text with line breaks (maximum three rendered lines), font selection, size, fill, outline color/width, shadow, alignment, position, and backing color/opacity. Support selecting heading text and applying an accent color so “Top 5” or “failed tattoo” can differ from the rest; persist text runs, not arbitrary HTML. Default Montserrat ExtraBold, 76 px, white with 6 px black outline. Wrap to available width, preserve explicit line breaks, and show overflow feedback.

Ranking controls: separate number and title font sizes/colors, outline/shadow, active-row accent color, optional per-rank number colors, row spacing, column position, title width, and title alignment. Defaults: numbers 96 px, titles 52 px, bold white with black outline, active number yellow. Clip names remain plain text; global title style applies to all names. Titles may wrap to two lines; shrink to the documented minimum (32 px), then require shortening or widening if still overflowing. Numbers scale down as needed but no smaller than 48 px. Do not silently clip text.

Preset selection changes visual settings only, never content/order/trims. Provide **Reset style**. Prevent export on unresolved text overflow; identify the offending field. Preview unsupported glyphs with a clear warning and provide a tested bundled fallback or require replacement; never silently drop emoji or characters in export.

Per-clip framing: **Fill/crop** default, **Fit with background** alternative, horizontal/vertical focal position, and zoom. Fill respects the preset's footage viewport; Fit preserves the entire source with the chosen solid background. Correct rotation metadata, preserve aspect ratio, and do not stretch. Display safe-area guides only in the editor.

## 8. Downloads and media lifecycle

Each slot progresses through empty → queued → downloading → processing → ready, or failed/cancelled. Include actionable messages and Retry; successful slots remain usable when another fails. Local uploads enter the same processing/ready path.

Download all schedules only populated unresolved slots, with at most two concurrent downloads. Treat a URL as one clip, not a playlist. YouTube Shorts and standard video URLs are supported; Instagram Reel retrieval depends on public access and extractor availability. Provider support is a requirement to implement and test, not a guarantee that every public link will download. Private, deleted, rate-limited, region-restricted, or login-required content gets a specific failure and local-upload alternative.

Validate HTTP(S) URLs, allowed provider hosts and media redirects. Disallow local/private-network fetch targets and arbitrary filesystem paths. Use downloader libraries or argument arrays, never interpolated shell commands. Apply bounded retries, timeouts, duration/file-size limits, and output-directory containment. Reuse current limits where suitable; expose the applicable limit in errors. Do not bypass access controls.

Probe downloaded/uploaded media before setting ready: validate video stream, usable duration, dimensions, rotation, and audio presence. Record asset metadata and store project-owned files. Duplicate URLs are allowed as separate entries with independent trims/names; caching may reuse immutable bytes but must retain correct ownership and cleanup.

Replacing a source retains name/rank/order/style, but resets trim and crop to valid defaults for the new source and tells the user. Use a per-slot generation token: old download completion cannot attach to a removed/replaced slot. Jobs also check project existence before committing assets. Clean up partial/stale files.

## 9. Persistence and API contract

Persist a versioned ranking document owned by Project (recommended dedicated `RankingComposition` table with unique project ID, schema version, revision, and JSON document). Assets remain MediaAsset rows owned by that same project. JSON is validated by typed backend schemas, not accepted unchecked.

Document fields:

- `schema_version`, `revision`, `project_id`.
- `canvas`: width, height, fps, preset, background, footage viewport.
- `heading`: text runs and style/layout settings.
- `ranking`: reveal policy (`on_clip_start_persist`), number/title styles, column geometry, active styling.
- `clips`: stable ID, rank, playback order, source URL/provider, asset ID (nullable), user name, trim in/out seconds, framing/zoom/focal point, volume, mute, source generation.
- `export`: output codec/profile settings; use fixed V1 defaults above.

Keep volatile job progress outside the composition. Persist enough operation identity/status to mark interrupted work on restart; do not leave permanent “downloading” or “rendering” spinners when an in-memory job disappears.

Proposed routes (names may be adjusted to local conventions while preserving behavior):

| Method/path | Contract |
| --- | --- |
| POST `/api/ranking/projects` | Create empty ranking project and five stable empty slots |
| GET `/api/ranking/projects/{id}` | Return document, revision, all media availability, and current job summaries |
| PUT `/api/ranking/projects/{id}` | Validate/save document with expected revision; return new revision, 409 on conflict |
| POST `/api/ranking/projects/{id}/clips/{clip_id}/download` | Start one source import with source generation; return job ID |
| POST `/api/ranking/projects/{id}/clips/{clip_id}/upload` | Attach uploaded video to that slot after validation |
| GET `/api/ranking/jobs/{job_id}` | Return type, project/clip identity, status, phase, progress, error/result |
| POST `/api/ranking/jobs/{job_id}/cancel` | Request cancellation and clean up partial output |
| POST `/api/ranking/projects/{id}/preview` | Start a draft render of an explicitly saved revision |
| POST `/api/ranking/projects/{id}/render` | Validate and freeze saved revision; return background render job ID |

The existing project list must recognize empty or partially missing ranking projects as openable. Show missing-source counts rather than treating the latest asset as the sole source. The frontend resumes through the ranking endpoint. Preserve existing standard/gaming contracts. Deletion cleans ranking document, all owned assets, jobs, and renders without deleting shared files owned elsewhere.

Autosave valid changes after a short debounce; flush before export/navigation, show Saving/Saved/Save failed, and retain local edits on failure. On 409, stop automatic writes and offer reload or save a separate project; do not silently overwrite newer edits. Invalid text can stay in local form state while clearly marked unsaved. A server restart must retain saved composition and completed source files.

`.vedit` export must retain project type, versioned composition, and all media references. Import remaps every asset reference to newly created assets and restores the ranking workspace. Missing files remain relinkable per slot; the project still opens. Extend version handling compatibly and keep old standard/gaming projects readable. Never silently import/export only one source of a ranking project.

## 10. Preview and render pipeline

Interactive preview switches source media using the same frame schedule as export and applies matching crop/layout overlays. Preload the next clip where feasible; pause on buffering instead of advancing over unseen footage. Seek resets reveal state deterministically. Display selected/active clip and total trimmed duration.

Use shared layout data and identical bundled fonts in frontend/backend. Prefer server-generated transparent text overlays or a shared layout manifest with fixed glyph positions for reliable wrapping/outline parity. CSS approximations alone are not proof of export fidelity. Provide **Render preview** using the same compositor as final export at reduced resolution; label it with its revision and mark it outdated after changes.

Final render:

1. Flush/save edits, validate all N entries (ready media, nonempty names, unique ranks/order, valid trims, no overflow), and freeze the composition revision and asset references.
2. Normalize each trimmed source to its output frame count, orientation, 30 fps, square pixels, and selected viewport/crop. Preserve source audio with volume/mute; create matching silence when absent. Normalize audio to stereo 48 kHz.
3. Composite the heading and ranking state over each segment. A title's reveal is controlled by global sequence start, not local source timestamps.
4. Concatenate normalized video/audio in playback order with no unintended gaps, repeated boundary frames, or accumulated A/V drift.
5. Encode MP4 (H.264, yuv420p, AAC, faststart); verify duration, streams, dimensions, and file readability before reporting success.
6. Publish a downloadable output associated with the frozen revision. Keep incomplete files separate and atomically promote completed output.

Render progress uses phases (Preparing, Rendering, Finalizing) and percentage where measurable. Cancellation terminates workers safely, removes partial outputs, and preserves source media/project. Failures preserve edits and provide Retry. Editing during a render is permitted; the render stays on its original snapshot and the UI marks it as an earlier version. Restrict to one active render per project; do not overwrite a previous successful export on failure.

Do not hardcode a claim about the current YouTube Shorts duration rules. Show total duration; this feature exports portrait MP4 and does not guarantee platform classification or upload acceptance.

## 11. Acceptance criteria and verification

1. New startup choice opens a dedicated empty five-slot ranking editor; all existing startup choices still work.
2. Five distinct source clips attach to one project. Download failure in slot three does not erase slots one/two or prevent retry/upload in slot three.
3. User can set heading, custom names, assigned ranks, and playback order. Dragging preserves each entry's identity and rank.
4. In sequence 5,4,3,2,1, ranking numbers remain arranged 1…5. At first frame only name five is visible; each subsequent name appears at its clip boundary, and previous names remain visible. Seeking backward removes names not yet reached.
5. Heading stays visible throughout; text and rank styling changes appear in preview and burned into export, including mixed heading colors and outlines.
6. Export contains exactly the requested trimmed sources in order, portrait dimensions and expected frame count, with continuous audio/silence and no unintended black boundary frames.
7. Landscape, portrait, rotated, mixed-rate, and silent inputs render without distortion or A/V drift. Crop/focal settings survive save and reopen.
8. Empty, complete, and missing-source projects reopen into Ranking Shorts, preserving order, names, heading, styles, trims, and available media.
9. Export is disabled with a specific reason when slots are missing, media is not ready, trims/ranks are invalid, or text overflows. No automatic omission of failed clips.
10. Replacement/removal during download cannot attach stale files; project deletion prevents background jobs from recreating it.
11. Cancel/retry, app restart, save failure, conflicting saves, and edit-during-render behave as defined above.
12. `.vedit` round trip restores all ranking data and assets; missing sources relink independently. Standard/gaming round trips remain compatible.

Verification plan for implementation: unit-test frame scheduling/reveal state and schema invariants; API tests for asset ownership, revision conflicts, imports, stale-job attachment, and resumption; a small synthetic render fixture with numbered/color-coded sources and tones/silence; inspect decoded frames immediately before/at/after each boundary and compare representative preview/output screenshots. Verify output with media probing and audio-duration checks. Add deterministic mocked provider failure tests and optional live smoke checks with permitted public links; network reliability must not gate unit tests. Run repository Python lint/format checks and relevant backend tests, plus frontend lint/build. Do not add an unrelated frontend test framework without assessing existing tooling.

## 12. Implementation handoff

This is a design document, not authorization to build the feature in this task. The next Codex implementation should re-read repository instructions and current changes, then plan work around: (1) document/storage and project routing, (2) slot imports and lifecycle, (3) editing/preview/styles, (4) rendering and export, (5) project portability and regression verification. Deliver the full workflow rather than a static editor mockup.

Builder-owned choices: internal module naming, exact component splits, overlay rasterization library, efficient FFmpeg/MoviePy plumbing, and job-registry implementation. Those choices must preserve the contracts, deterministic frame schedule, persistence, and acceptance criteria above.
