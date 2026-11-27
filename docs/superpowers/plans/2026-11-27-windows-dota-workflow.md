# Windows Dota Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a fresh native-Windows clone installable and reliable for cutting one full Dota gameplay recording from death until respawn or buyback.

**Architecture:** Retain the existing FastAPI/React application and golden-respawn-box detector. Add PowerShell orchestration around the locked Python and frontend dependencies, harden the detector's end-of-stream state transition, and document the exact user workflow.

**Tech Stack:** PowerShell, Python 3.11, FastAPI, React/Vite, pytest, uv

**Spec:** `docs/superpowers/specs/2026-11-27-windows-dota-workflow-design.md`

## Global Constraints

- Support one full gameplay recording, not batch uploads.
- Native Windows PowerShell is the installation path.
- Preserve all unrelated working-tree changes.
- Death cuts do not require OCR or API credentials.
- The user must select the correct hero slot and use a visible standard Dota HUD.

## Review Focus

- A recording ending while dead keeps the cut through the final sample.
- A single timer dropout does not split or truncate a dead interval.
- A quick buyback closes the interval as soon as the alive state is confirmed.
- Setup stops with an actionable message when uv or Node is unavailable.
- Startup cleans up the backend process when Vite exits.

---

### Task 1: Harden end-of-recording death handling

**Files:**
- Modify: `backend/features/gaming/death_detect.py`
- Test: `backend/tests/test_death_detect.py`

**Interfaces:**
- Consumes: `_dead_state_runs(times, signal, threshold, enter_samples, exit_samples)`
- Produces: dead intervals whose end is not shortened by an unconfirmed final-state flicker

- [ ] Add a failing test for a death followed by fewer than `exit_samples` alive samples at EOF.
- [ ] Run the focused test and confirm it fails with an early interval end.
- [ ] Make EOF use the next sample boundary unless the alive transition was fully confirmed.
- [ ] Run the death detector tests and full backend suite.

### Task 2: Add native Windows setup and startup

**Files:**
- Create: `scripts/setup-windows.ps1`
- Create: `scripts/start-windows.ps1`

**Interfaces:**
- Produces: `powershell -ExecutionPolicy Bypass -File scripts/setup-windows.ps1`
- Produces: `powershell -ExecutionPolicy Bypass -File scripts/start-windows.ps1`

- [ ] Add setup preflight checks and locked Python/frontend installation.
- [ ] Add startup orchestration, health wait, and backend cleanup.
- [ ] Parse both scripts with PowerShell when available; otherwise review their syntax and document that native execution remains pending.

### Task 3: Document the supported Dota workflow

**Files:**
- Modify: `README.md`
- Modify: `QUICKSTART.md`

**Interfaces:**
- Consumes: the two PowerShell scripts from Task 2
- Produces: a fresh-clone Windows guide and step-by-step death-cut workflow

- [ ] Document prerequisites, setup, launch, UI workflow, no-key core operation, standard-HUD assumptions, and output location.
- [ ] Remove Unix-only recovery commands from the Windows-facing quick path.
- [ ] Verify every documented command matches the scripts and repository paths.

### Task 4: Clean and verify the deliverable

**Files:**
- Modify: `backend/app.py`

**Interfaces:**
- Produces: clean Python lint, frontend lint/build, and full backend tests

- [ ] Fix the two existing SQLModel boolean-comparison lint findings without changing query behavior.
- [ ] Run `ruff check .` and `black --check .`.
- [ ] Run `pytest`.
- [ ] Run `npm run lint` and `npm run build` in `frontend`.
- [ ] Inspect `git diff --check` and the final scoped diff.
