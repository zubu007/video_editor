1.  Create a progress bar for rendering
2. Option to confirm silence cuts

## Gaming video mode (Dota 2 — support/saves content)

Planned for the "Edit a gaming video" start-screen option. Waiting on a sample
recording to calibrate CV thresholds before implementation.

3. **Cut death time (CV-based)** — ✅ BUILT, VALIDATED & WIRED INTO THE APP
   - Module: `backend/features/gaming/death_detect.py` →
     `detect_death_intervals(video)` returns `[{start, end, duration}]` dead
     ranges in source seconds. Validated on the full sample game (1920×1080/60,
     34.8 min): auto-identified the player slot (0.95 conf) and found 3 solid
     deaths — 354→361s (7s), 558→576s (18s), 2077→2083s (6s) — in ~90s.

   **Findings from the sample footage (IMPORTANT — don't relearn):**
   - ❌ **Grayscale approach ruled out.** Modern Dota does NOT desaturate the
     screen on death (verified: central saturation never collapses; while dead
     you free-look over the colourful map). The original plan does not work.
   - ❌ **Bottom HUD is selection-dependent** — clicking another unit shows their
     portrait/HP/respawn there, so never use it as the dead signal.
   - ❌ **Top-bar portrait grey-out is too noisy** — mean saturation of the slot
     did not cleanly separate dead/alive.
   - ✅ **Player's slot = colour-signature match.** Bottom hero globe vs top-bar
     icon are different art, so match a *masked HSV Hue-Sat histogram* (hero
     palette is the cross-art invariant), voted over ~15 early frames. Correctly
     locked slot 5 (Vengeful Spirit/Support), margin 0.33. Fixed all game →
     immune to teamfight simultaneous deaths.
   - ✅ **Dead signal = golden respawn-box** under the player's fixed slot: a
     gold-bordered countdown box present only while dead. Detect the fraction of
     gold-hue pixels (OpenCV H 12–32, S>110, V>140) in the box region; a
     *continuous* run >5s = a death. Clean (median 0, ~0.077 during deaths).
     Handles buyback/Aegis (box vanishes early). Do NOT merge runs across gaps —
     a solid box never flickers, so gaps are noise, not one death.
   - ✅ **K/D/A deaths OCR** (top-left, tesseract) is a clean death-*event*
     signal over short spans but too noisy to anchor over a full match; kept as
     optional `use_ocr` confirmation tag only (default off, no tesseract needed).
   - Ultra-short early respawns (~<5s, e.g. the sample's first death ~177s) are
     intentionally skipped — not worth cutting.
   - Coordinates/thresholds live in `DotaHudLayout` (calibrated 1920×1080,
     `.scaled()` for other resolutions). Dire slot centres are calibrated too
     (measured from the sample footage's top bar via the player-colour strips;
     symmetric to Radiant about the frame centre within ~1px). Tests:
     `backend/tests/test_death_detect.py` (pure fns; full-video test gated
     behind `DEATH_DETECT_SLOW`).
   - **Gold respawn box = the local player's box only.** A dead *teammate's*
     countdown box is plain grey (verified on the sample: the player's own box
     is gold-bordered, a teammate's is not, same game) — which is why teammate
     deaths don't false-positive. Assumed to hold for a Dire local player;
     not yet verified against a Dire-side recording.
   - **Slot auto-ID samples mid-game (25–85% of duration), not the first 3
     minutes.** Recordings that include the pick phase / pre-game strategy
     screens have completely different top-bar layouts there (draft cards with
     gold rank medals that also fake out the respawn-box signal), which
     poisoned the vote and returned a confidently wrong slot.

   **App wiring (done):**
   - "Edit a gaming video" start card → normal upload flow with `isGaming` set →
     a **"Deaths"** side-panel tab (`EditorTools/DeathCutsPanel`).
   - Background job (`features/gaming/jobs.py`) + endpoints:
     `POST /api/gaming/detect-deaths/{file_id}` (params `team`, `player_slot`,
     `use_ocr`), `GET /api/gaming/death-detect/status/{job_id}`, and
     `GET /api/gaming/slot-preview/{file_id}` (auto slot + 5 base64 portrait
     thumbnails for the manual selector). Detected intervals are saved as `cut`
     EditOperations (`source="death_detection"`) via the existing edit endpoint,
     so render/timeline work for free.
   - **Manual slot selector (backup):** the panel shows the 5 team portraits with
     the auto-detected one highlighted; the user can click their hero to override
     and re-detect with that `player_slot`. Handles the case where the colour
     match is wrong or teamfight deaths confuse auto-ID.

   **Still open:**
   - Verify death detection on a real Dire-side recording (centres are
     calibrated and the gold box is believed to be the local player's marker on
     both teams, but no Dire footage has been through the pipeline yet).
   - Pick-phase gold rank medals can register as a false "death" run at the very
     start of a recording if they land under the chosen slot centre (observed
     under a mid-bar slot; the sample's slot 4 escapes it). Consider ignoring
     respawn runs that begin before the first K/D/A read or clock detection.
   - Optional: auto-detect team; padding control for the death cuts; a progress
     signal during the ~90s scan (currently indeterminate "Scanning…").

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
