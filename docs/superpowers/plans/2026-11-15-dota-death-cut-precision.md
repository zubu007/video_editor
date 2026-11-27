# Precise Dota 2 Death Cuts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce precise click-independent Dota 2 death cuts from a manually selected top portrait, including quick buybacks and exact return-to-play boundaries.

**Architecture:** Use a persistence-based state machine for a coarse top-HUD scan, then decode small windows around candidate transitions at a higher frame rate. Require an explicit portrait selection in the death-cuts UI while preserving existing auto-selection as a visual suggestion only.

**Tech Stack:** Python 3.11, OpenCV, ffmpeg/imageio-ffmpeg, pytest, React 19, Vite, ESLint.

**Spec:** `docs/superpowers/specs/2026-11-15-dota-death-cut-precision-design.md`

## Global Constraints

- Use only the selected fixed top portrait and its respawn timer for death windows.
- The first stable timer disappearance ends both buyback and ordinary-respawn cuts.
- Do not discard dead intervals merely because they last less than five seconds.
- Preserve the user's configurable post-death cut-start delay.
- Do not alter the separate K/D/A marker workflow.

## Review Focus

- A one-frame timer dropout during a death must not split or end the interval.
- A buyback shorter than five seconds must still produce an interval.
- Refined boundaries must return the first frame of a stable transition, not the confirmation frame.
- Failed refinement must fall back to coarse boundaries.
- Detection must remain disabled until the user explicitly selects a portrait.

---

### Task 1: Persistent timer-state detection and boundary refinement

**Files:**
- Modify: `backend/features/gaming/death_detect.py`
- Test: `backend/tests/test_death_detect.py`

**Interfaces:**
- Produces: `_dead_state_runs(...) -> list[dict]`, `_stable_transition_time(...) -> float | None`, and `_refine_dead_interval(...) -> dict`.
- Consumes: existing `_respawn_signal`, `DotaHudLayout`, and ffmpeg top-strip decoding.

- [ ] Write failing unit tests for flicker bridging, quick buybacks, first-frame stable transitions, and refinement fallback.
- [ ] Run the focused tests and confirm they fail for the missing interfaces/old five-second behavior.
- [ ] Implement the state machine, windowed top-strip decoder, and refined transition helpers.
- [ ] Run `pytest backend/tests/test_death_detect.py -q` and confirm the focused suite passes.

### Task 2: Integrate coarse-to-fine detection into the pipeline

**Files:**
- Modify: `backend/features/gaming/death_detect.py`
- Modify: `backend/app.py`
- Test: `backend/tests/test_death_detect.py`
- Test: `backend/tests/test_project_workflow.py`

**Interfaces:**
- Consumes: Task 1's state runs and interval refinement.
- Produces: precise intervals through `detect_death_intervals` and `detect_gaming_markers`; validates `player_slot` in the HTTP route.

- [ ] Write failing pipeline tests proving short intervals survive and refinement is applied.
- [ ] Run the focused tests and confirm the old pipeline fails them.
- [ ] Replace fixed minimum-duration filtering with persistent state runs and refine every candidate boundary.
- [ ] Add route validation for slot values outside `0..4`.
- [ ] Run the backend gaming and workflow tests.

### Task 3: Require explicit portrait selection in the editor

**Files:**
- Modify: `frontend/src/components/EditorTools/DeathCutsPanel.jsx`
- Modify: `frontend/src/App.jsx`

**Interfaces:**
- Consumes: existing portrait previews and `deathSelectedSlot` state.
- Produces: a detection action that cannot start until the user explicitly chooses a portrait.

- [ ] Update the panel to make portrait selection a required step and disable detection without it.
- [ ] Guard the application handler against programmatic detection without a selected slot.
- [ ] Preserve auto-slot highlighting as a suggestion without treating it as selection.
- [ ] Run `npm run lint` and `npm run build`.

### Task 4: Full verification and documentation alignment

**Files:**
- Modify: `TODO.md`
- Modify: `CLAUDE.md`

**Interfaces:**
- Consumes: completed detector and UI behavior.
- Produces: accurate developer notes and verification evidence.

- [ ] Update Dota detection documentation to describe manual selection, coarse-to-fine refinement, and buyback handling.
- [ ] Run Ruff on modified Python files.
- [ ] Run the full backend test suite and report any pre-existing failures separately.
- [ ] Run frontend lint and production build.

