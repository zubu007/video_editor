# Precise Dota 2 Death Cuts Design

## Intent

Make automated Dota 2 death cuts precise and click-independent. The user selects
their hero in the fixed top portrait bar before scanning. Detection uses only
that portrait slot and its respawn timer, so selecting other heroes during play
cannot change the tracked player.

## Goals

- Require an explicit top-bar hero selection before death detection.
- Detect the first stable appearance of the selected portrait's respawn timer.
- Detect the first stable disappearance of that timer as the return-to-play
  boundary for both normal respawns and buybacks.
- Preserve quick buybacks instead of discarding dead intervals under five seconds.
- Produce sub-second boundaries without decoding the entire match at full rate.
- Keep the existing configurable post-death delay for the start of the cut; the
  cut always ends at the detected return-to-play boundary.

## Non-goals

- Distinguishing a buyback from a normal respawn in the returned data.
- Reading the currently selected unit's bottom HUD.
- Requiring match IDs, replay files, or network match data.
- Replacing the separate K/D/A marker feature.

## Architecture

The detector performs a coarse scan of the narrow top HUD strip to find candidate
dead intervals for the user-selected slot. A persistence-based state machine
bridges brief signal flicker and accepts short dead intervals. Around each coarse
transition it decodes only a small time window at a higher frame rate and returns
the first frame of the stable state transition. The same timer-disappearance
transition ends both normal-respawn and buyback cuts.

The frontend requires the user to load the five top portraits and click their
hero before enabling detection. Existing auto-identification may still highlight
a suggestion, but it is not accepted as the user's choice.

## Approaches considered

1. **Coarse-to-fine top-portrait timer detection — selected.** Works from any
   recording, is unaffected by bottom-HUD selection, handles buyback naturally,
   and limits expensive high-rate decoding to transition windows.
2. **Match/replay event synchronization.** More authoritative, but requires a
   match ID or replay and reliable video-to-game-clock synchronization.
3. **General OCR or a trained video model.** OCR is noisy on the tiny HUD and a
   learned model requires a representative labelled dataset. Either can remain
   optional corroboration, not the primary boundary source.

## Failure handling

- Brief timer dropouts do not end a death until the alive state persists.
- A quick buyback is retained even when the dead state lasts under five seconds.
- Empty or invalid slot selections are rejected at the API boundary.
- If high-rate refinement cannot read a transition, the coarse boundary remains
  available rather than losing the entire interval.

