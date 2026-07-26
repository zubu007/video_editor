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

4. **Manual streaming captions (typewriter effect)** — ✅ DONE
   - User pauses at the playhead, types a note (e.g. a thought or item-choice
     explanation) in the new **Notes** tab, and it's placed at that time and
     streams on with a typewriter reveal.
   - Implemented as a separate `text_caption` edit type (distinct from the
     transcript "Captions" tab):
     - Backend `features/captions/text_caption.py` — typewriter ASS builder
       (`build_text_caption_ass`) + `add_text_captions` burn; registered in
       `SUPPORTED_EDIT_TYPES`, validated, remapped source→output time, and burned
       as a final ffmpeg pass in `_execute_render` (chained after transcript
       captions).
     - Frontend `EditorTools/TextCaptionsPanel` (add-at-playhead, edit, position,
       toggle, delete) + live `VideoPlayer/TextCaptionOverlay` typewriter preview.
   - Tests: `backend/tests/test_text_captions.py`.
   - Possible follow-ups: timeline lane for notes (drag/trim), per-note reveal
     speed control in the UI, style presets for the note box.

### Later (support-specific, after the above prove out)
- Cut long farming/downtime stretches.
- "Save" detection: ally health bars hitting critical then recovering (CV on the
  top ally HP bars), ideally near the player's heal casts.
- Auto text callouts ("Clutch save!") over detected save moments.
