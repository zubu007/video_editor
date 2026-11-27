# Windows Dota Workflow Design

## Intent

Make a fresh Windows clone usable for one complete Dota 2 gameplay recording: upload the recording, select the player's hero slot, detect every dead interval, save those intervals as cuts, render, and download the edited video.

## Goals

- Provide repeatable PowerShell setup and startup commands for a fresh clone.
- Keep death detection independent of Tesseract and API keys.
- Cut from shortly after the detected death until normal respawn, buyback, or Aegis return.
- Preserve a death interval when the recording ends before the player returns alive.
- Document the real UI workflow and its standard-HUD assumptions.

## Non-goals

- Batch upload or folder processing.
- Automatic YouTube upload.
- Redesigning the editor or adding a different Dota telemetry source.
- Supporting cropped or hidden HUD recordings.

## Constraints

- Native Windows PowerShell is the supported handoff path.
- Python 3.11 is used for the locked Python environment.
- Node.js 20 or newer is required for the Vite frontend.
- The detector remains calibrated for a visible standard Dota HUD; the user explicitly selects the hero slot before scanning.
- Existing unrelated working-tree changes must be preserved.

## Approaches

1. Document manual commands only. This adds little code, but leaves installation mistakes and two-process startup to the user.
2. Add PowerShell setup/start scripts plus a focused detector regression test. This is the selected approach because it makes the existing web app reproducible without changing the editing workflow.
3. Package a Windows desktop executable. This would be a separate distribution project and is unnecessary for the requested personal Windows setup.

## Design

`scripts/setup-windows.ps1` validates Git/uv/Node, creates the Python 3.11 environment from `uv.lock`, installs the frontend with `npm ci`, and explains that Tesseract is optional for K/D/A markers. `scripts/start-windows.ps1` starts the FastAPI backend without reload, waits for its health endpoint, runs Vite in the foreground, and stops the backend when the frontend exits.

The existing golden-respawn-box detector remains authoritative. Its persistent state machine already distinguishes short buybacks from one-sample HUD flicker. At end of stream, an unconfirmed alive sample must not truncate a still-dead interval; only a fully confirmed exit ends it early.

The README will describe the exact workflow and limits. Core death cutting needs no LLM key, Pexels key, Whisper model, or Tesseract installation.
