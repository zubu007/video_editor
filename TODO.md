1.  Create a progress bar for rendering
2. Option to confirm silence cuts

## Gaming video mode (Dota 2 — support/saves content)

Planned for the "Edit a gaming video" start-screen option. Waiting on a sample
recording to calibrate CV thresholds before implementation.

3. **Cut death time (CV-based)**
   - Detect when the player's hero is dead by the Dota 2 death-screen grayscale:
     the screen desaturates (+ dark vignette + respawn timer) while dead and snaps
     back to full color on respawn/buyback.
   - Approach: sample frames (a few fps), measure color saturation in the central
     screen region; a sustained low-saturation stretch = a death period. No ML/game
     integration needed; numpy on sampled frames.
   - New module `features/gaming/death_detect.py` returning `{start, end}` ranges
     (pad + reuse `audio_pause`'s `merge_nearby_pauses`).
   - Feed ranges into the existing cut pipeline: `video_cutter/cut.py` already
     *removes* given ranges and keeps the rest, and they save as `cut`
     EditOperations that render + show on the timeline for free.
   - NEEDS: a 2-3 min sample clip that includes at least one death→respawn, plus
     the capture resolution, to tune the saturation threshold.

4. **Manual streaming captions (typewriter effect)**
   - User pauses at the playhead where they want a note, types a caption (e.g. a
     thought or item-choice explanation), and it's placed at that time with a
     dynamic streaming/typewriter reveal.
   - Confirmed feasible: reuses the existing caption engine. `captions/ass_builder.py`
     already emits per-word ASS events (streaming = word/char-granularity reveal via
     ASS `\k` or sequential events); `VideoPlayer/CaptionOverlay` gives the live CSS
     preview before render.
   - Design: a SEPARATE edit type from the transcript-based "Captions" tab — a
     manual `text_caption` overlay (custom text, placed at the paused time, own
     reveal style). Keep it distinct so auto-captions and manual notes don't collide;
     allows many independent captions on the timeline.

### Later (support-specific, after the above prove out)
- Cut long farming/downtime stretches.
- "Save" detection: ally health bars hitting critical then recovering (CV on the
  top ally HP bars), ideally near the player's heal casts.
- Auto text callouts ("Clutch save!") over detected save moments.
