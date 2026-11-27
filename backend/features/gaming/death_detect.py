"""Detect a player's death/alive intervals in a Dota 2 gameplay recording.

The approach is HUD-driven, not scene-driven — modern Dota does *not* desaturate
the screen on death, so a whole-frame grayscale detector finds nothing (verified
empirically). Instead we read the standard HUD:

* **Which portrait is the player's** — the top hero bar has one fixed slot per
  team member for the whole game. We identify the player's slot once by matching
  the colour signature of the bottom hero globe (the player's own hero) against
  the five team slots (:func:`identify_player_slot`). The globe and the top-bar
  icon are different art, so we match on a masked HSV colour histogram (the hero
  palette is shared across both renderings) rather than by template correlation.

* **When the player is dead** — that fixed top-bar portrait desaturates (greys
  out) while dead and returns to colour on respawn, so a drop in the slot's mean
  saturation marks the dead interval. This naturally handles buyback/Aegis (the
  portrait re-colours early).

* **Corroboration (optional)** — the top-left ``K / D / A`` readout's middle
  number steps up exactly on each death; when tesseract is available we OCR it to
  confirm each grey-out run is a real death and to pin the start precisely.

All coordinates in :class:`DotaHudLayout` are calibrated for a 1920x1080 HUD and
scaled for other resolutions. Time ranges are returned in source-video seconds,
in the ``{"start", "end"}`` shape the rest of the pipeline speaks.
"""

from __future__ import annotations

import logging
import re
import subprocess
from collections import Counter
from dataclasses import dataclass, replace
from pathlib import Path

import cv2
import imageio_ffmpeg
import numpy as np

from backend.features.gaming.ocr import (
    DEFAULT_OCR_ENGINE,
    engine_available,
    read_digits,
)

logger = logging.getLogger(__name__)

# HSV colour-signature bins (Hue x Saturation) for hero matching.
_H_BINS, _S_BINS = 24, 8
# A pixel counts toward a hero's colour signature only if it is saturated and
# bright enough — this masks out dark backgrounds and grey UI chrome.
_SIG_MIN_SAT, _SIG_MIN_VAL = 40, 40

# Slot-match acceptance: the best team slot must beat the runner-up by this
# correlation margin to cast a confident vote.
_MATCH_MIN_MARGIN = 0.08
_MATCH_MIN_SCORE = 0.15

# Respawn-box end detection. While dead, a golden-bordered countdown box sits
# under the player's portrait; its golden pixels are absent otherwise. A sample
# is "dead" when the golden fraction in that region exceeds this threshold.
# (Grey-out of the portrait itself proved too noisy to use.)
_GOLD_H_LO, _GOLD_H_HI = 12, 32  # OpenCV hue range for the box's gold border
_GOLD_MIN_SAT, _GOLD_MIN_VAL = 110, 140
_GOLD_FRACTION = 0.03
# Coarse scan and state persistence. The state machine confirms transitions
# instead of filtering by total dead duration: a quick buyback can legitimately
# end the timer in under five seconds, while a one-sample dropout is just HUD
# flicker and must not end the interval.
_COARSE_FPS = 2.0
_COARSE_ENTER_SAMPLES = 2
_COARSE_EXIT_SAMPLES = 2

# Candidate transitions are re-decoded only in this small neighbourhood. At
# 15 fps, three stable frames give a 200 ms persistence check while preserving
# the first frame of the transition as the returned boundary.
_REFINE_FPS = 15.0
_REFINE_WINDOW_SECONDS = 1.5
_REFINE_STABLE_SAMPLES = 3
# A run is "K/D/A-confirmed" if a deaths increment lands within this window of
# its start (optional corroboration only).
_DEATH_MATCH_WINDOW = 8.0


@dataclass(frozen=True)
class DotaHudLayout:
    """Pixel geometry of the Dota HUD elements this detector reads.

    Defaults are calibrated for a 1920x1080 recording with the standard HUD.
    Use :meth:`scaled` to adapt to another resolution.

    Boxes are ``(x0, y0, x1, y1)``. ``*_centers`` are the horizontal centres of
    the five team portrait slots in the top hero bar; the portrait face is the
    band ``[top_y0, top_y1]`` around each centre, ``top_half`` wide.
    """

    width: int = 1920
    height: int = 1080
    kda_box: tuple[int, int, int, int] = (0, 63, 210, 83)
    bottom_globe_box: tuple[int, int, int, int] = (528, 950, 652, 1046)
    top_y0: int = 8
    top_y1: int = 38
    top_half: int = 22
    # Respawn countdown box sits just below the portrait; band around the slot
    # centre, `respawn_half` wide.
    respawn_y0: int = 42
    respawn_y1: int = 74
    respawn_half: int = 30
    radiant_centers: tuple[int, ...] = (564, 634, 696, 755, 816)
    # Dire slots mirror Radiant about the frame centre (measured on sample
    # footage via the player-colour bars: symmetric to within ~1px).
    dire_centers: tuple[int, ...] = (1098, 1160, 1222, 1284, 1346)

    def scaled(self, width: int, height: int) -> DotaHudLayout:
        """Return a copy scaled from the calibrated size to ``width x height``."""
        if width == self.width and height == self.height:
            return self
        sx, sy = width / self.width, height / self.height

        def sbox(box: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
            x0, y0, x1, y1 = box
            return (round(x0 * sx), round(y0 * sy), round(x1 * sx), round(y1 * sy))

        return replace(
            self,
            width=width,
            height=height,
            kda_box=sbox(self.kda_box),
            bottom_globe_box=sbox(self.bottom_globe_box),
            top_y0=round(self.top_y0 * sy),
            top_y1=round(self.top_y1 * sy),
            top_half=round(self.top_half * sx),
            respawn_y0=round(self.respawn_y0 * sy),
            respawn_y1=round(self.respawn_y1 * sy),
            respawn_half=round(self.respawn_half * sx),
            radiant_centers=tuple(round(c * sx) for c in self.radiant_centers),
            dire_centers=tuple(round(c * sx) for c in self.dire_centers),
        )

    def team_centers(self, team: str) -> tuple[int, ...]:
        """Portrait-slot centres for ``team`` (``"radiant"`` or ``"dire"``)."""
        if team == "radiant":
            return self.radiant_centers
        if team == "dire":
            if not self.dire_centers:
                raise ValueError("Dire slot centres are not calibrated.")
            return self.dire_centers
        raise ValueError(f"Unknown team '{team}' (expected 'radiant' or 'dire').")

    def respawn_box(self, center: int) -> tuple[int, int, int, int]:
        """Respawn-countdown box region under the slot at ``center``."""
        return (
            center - self.respawn_half,
            self.respawn_y0,
            center + self.respawn_half,
            self.respawn_y1,
        )

    @property
    def strip_height(self) -> int:
        """Height of the top HUD strip covering K/D/A, portraits, respawn box.

        Rounded up to an even number: ffmpeg's ``crop`` snaps odd dimensions to
        even, and a mismatch between the requested and produced height desyncs
        the raw-frame reader.
        """
        h = max(self.kda_box[3], self.top_y1, self.respawn_y1) + 4
        return h + (h % 2)


def _ffmpeg_exe() -> str:
    return imageio_ffmpeg.get_ffmpeg_exe()


def _video_dimensions(video_path: str | Path) -> tuple[int, int]:
    """Return the ``(width, height)`` of a video via ffprobe/ffmpeg metadata."""
    width, height, _ = _video_metadata(video_path)
    return width, height


def _video_metadata(video_path: str | Path) -> tuple[int, int, float]:
    """Return the ``(width, height, duration_seconds)`` of a video."""
    from moviepy import VideoFileClip

    clip = VideoFileClip(str(video_path))
    try:
        return int(clip.w), int(clip.h), float(clip.duration or 0.0)
    finally:
        clip.close()


def _default_sample_times(duration: float, count: int = 14) -> list[float]:
    """Sample times spread across the middle of the recording.

    Recordings often include the pick phase and pre-game strategy screen, where
    the top bar uses entirely different layouts (draft cards, lane assignments)
    — sampling there poisons the slot vote. The portrait slots are fixed for the
    whole match, so the mid-game stretch (25–85% of the duration) is both safe
    and representative. Falls back to an early-game spread when the duration is
    unknown.
    """
    if duration <= 0:
        return [float(t) for t in range(40, 200, 12)]
    lo, hi = 0.25 * duration, 0.85 * duration
    step = (hi - lo) / max(count - 1, 1)
    return [lo + i * step for i in range(count)]


def _extract_frame(
    video_path: str | Path, t: float, width: int, height: int
) -> np.ndarray:
    """Decode a single BGR frame at ``t`` seconds."""
    cmd = [
        _ffmpeg_exe(),
        "-v",
        "error",
        "-ss",
        f"{t:.3f}",
        "-i",
        str(video_path),
        "-frames:v",
        "1",
        "-pix_fmt",
        "bgr24",
        "-f",
        "rawvideo",
        "-",
    ]
    result = subprocess.run(cmd, capture_output=True)
    expected = width * height * 3
    if len(result.stdout) < expected:
        raise RuntimeError(f"Could not read a frame at t={t:.1f}s")
    return np.frombuffer(result.stdout[:expected], np.uint8).reshape(height, width, 3)


def _crop(image: np.ndarray, box: tuple[int, int, int, int]) -> np.ndarray:
    x0, y0, x1, y1 = box
    return image[y0:y1, x0:x1]


def _colour_signature(bgr: np.ndarray) -> np.ndarray:
    """Masked HSV Hue-Saturation histogram of a crop, L1-normalised.

    Only saturated, non-dark pixels contribute, so dark backgrounds and grey UI
    chrome are ignored and the hero's own palette dominates — the invariant that
    survives the globe-vs-icon art difference.
    """
    if bgr.size == 0:
        return np.zeros((_H_BINS, _S_BINS), np.float32)
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    sat, val = hsv[..., 1], hsv[..., 2]
    mask = ((sat > _SIG_MIN_SAT) & (val > _SIG_MIN_VAL)).astype(np.uint8)
    hist = cv2.calcHist([hsv], [0, 1], mask, [_H_BINS, _S_BINS], [0, 180, 0, 256])
    total = float(hist.sum())
    return hist / total if total > 0 else hist


def _slot_box(center: int, layout: DotaHudLayout) -> tuple[int, int, int, int]:
    return (
        center - layout.top_half,
        layout.top_y0,
        center + layout.top_half,
        layout.top_y1,
    )


def _match_slot(
    bottom_sig: np.ndarray, slot_sigs: list[np.ndarray]
) -> tuple[int, float]:
    """Best-matching slot index and its correlation margin over the runner-up."""
    scores = [
        float(cv2.compareHist(bottom_sig, s, cv2.HISTCMP_CORREL)) for s in slot_sigs
    ]
    order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
    best = order[0]
    margin = scores[best] - (scores[order[1]] if len(order) > 1 else 0.0)
    return best, margin if scores[best] >= _MATCH_MIN_SCORE else -1.0


def identify_player_slot(
    video_path: str | Path,
    layout: DotaHudLayout | None = None,
    team: str = "radiant",
    sample_times: list[float] | None = None,
) -> tuple[int, float]:
    """Identify which top-bar team slot is the player's hero.

    Matches the bottom hero globe's colour signature against the team slots over
    several early frames and takes the confidence-weighted majority vote, so a
    frame where the player had clicked another unit can't decide the result.

    Args:
        video_path: The gameplay recording.
        layout: HUD geometry; defaults to the calibrated layout scaled to the
            video's resolution.
        team: The player's team (``"radiant"`` or ``"dire"``).
        sample_times: Seconds to sample; defaults to a spread across the middle
            of the recording (avoiding pick-phase/pre-game HUD layouts).

    Returns:
        tuple[int, float]: ``(slot_index, confidence)`` — the 0-based slot and a
        vote-share confidence in ``[0, 1]``. Confidence 0 means no confident vote.
    """
    width, height, duration = _video_metadata(video_path)
    layout = (layout or DotaHudLayout()).scaled(width, height)
    centers = layout.team_centers(team)
    if sample_times is None:
        sample_times = _default_sample_times(duration)

    votes: Counter[int] = Counter()
    weight = 0.0
    for t in sample_times:
        try:
            frame = _extract_frame(video_path, t, width, height)
        except RuntimeError:
            continue
        bottom_sig = _colour_signature(_crop(frame, layout.bottom_globe_box))
        slot_sigs = [
            _colour_signature(_crop(frame, _slot_box(c, layout))) for c in centers
        ]
        slot, margin = _match_slot(bottom_sig, slot_sigs)
        if margin >= _MATCH_MIN_MARGIN:
            votes[slot] += margin
            weight += margin

    if not votes:
        raise RuntimeError("Could not identify the player's hero slot from the HUD.")
    slot, slot_weight = votes.most_common(1)[0]
    return slot, (slot_weight / weight if weight else 0.0)


def extract_slot_previews(
    video_path: str | Path,
    team: str = "radiant",
    layout: DotaHudLayout | None = None,
    sample_time: float | None = None,
) -> tuple[int, float, list[np.ndarray]]:
    """Return the auto-identified slot plus a thumbnail of each team portrait.

    Powers the app's manual slot selector: the user sees the five team portraits
    (with the auto-detected one highlighted) and can pick the right one if the
    colour match got it wrong.

    Args:
        video_path: The gameplay recording.
        team: The player's team (``"radiant"`` or ``"dire"``).
        layout: HUD geometry; defaults to the calibrated layout for the video's
            resolution.
        sample_time: Frame time to cut the thumbnails from; defaults to a
            mid-game moment where the standard top bar (not a pick-phase or
            pre-game layout) is on screen.

    Returns:
        tuple[int, float, list[np.ndarray]]: ``(auto_slot, confidence, thumbs)``
        where ``thumbs`` are BGR crops of the five team portraits in slot order.
    """
    width, height, duration = _video_metadata(video_path)
    layout = (layout or DotaHudLayout()).scaled(width, height)
    centers = layout.team_centers(team)

    try:
        auto_slot, confidence = identify_player_slot(video_path, layout, team)
    except RuntimeError:
        auto_slot, confidence = -1, 0.0

    if sample_time is None:
        sample_time = 0.4 * duration if duration > 0 else 90.0
    frame = _extract_frame(video_path, sample_time, width, height)
    # Slightly enlarged portrait crop (whole icon, not just the face) for display.
    pad_x = layout.top_half + round(6 * width / layout.width)
    thumbs = [
        frame[0 : layout.respawn_y0, max(0, c - pad_x) : c + pad_x].copy()
        for c in centers
    ]
    return auto_slot, confidence, thumbs


def _stream_top_strip(video_path: str | Path, fps: float, width: int, strip_h: int):
    """Yield ``(t_seconds, bgr_strip)`` for the top HUD strip at ``fps``."""
    cmd = [
        _ffmpeg_exe(),
        "-v",
        "error",
        "-i",
        str(video_path),
        "-vf",
        f"fps={fps},crop={width}:{strip_h}:0:0",
        "-pix_fmt",
        "bgr24",
        "-f",
        "rawvideo",
        "-",
    ]
    frame_bytes = width * strip_h * 3
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, bufsize=frame_bytes * 8)
    index = 0
    try:
        while True:
            # Read exactly one frame; a short read means end-of-stream.
            buf = proc.stdout.read(frame_bytes)
            while 0 < len(buf) < frame_bytes:
                more = proc.stdout.read(frame_bytes - len(buf))
                if not more:
                    break
                buf += more
            if len(buf) < frame_bytes:
                break
            strip = np.frombuffer(buf, np.uint8).reshape(strip_h, width, 3)
            yield index / fps, strip
            index += 1
    finally:
        proc.stdout.close()
        proc.wait()


def _stream_top_strip_window(
    video_path: str | Path,
    start: float,
    end: float,
    fps: float,
    width: int,
    strip_h: int,
):
    """Yield top-HUD frames for a short source-time window.

    The full match is scanned coarsely; this decoder is used only around a
    candidate timer appearance/disappearance so the final boundaries retain
    sub-second precision without paying full-rate decode cost for the match.
    """
    start = max(0.0, float(start))
    duration = max(0.0, float(end) - start)
    if duration <= 0:
        return
    cmd = [
        _ffmpeg_exe(),
        "-v",
        "error",
        "-ss",
        f"{start:.6f}",
        "-i",
        str(video_path),
        "-t",
        f"{duration:.6f}",
        "-vf",
        f"fps={fps},crop={width}:{strip_h}:0:0",
        "-pix_fmt",
        "bgr24",
        "-f",
        "rawvideo",
        "-",
    ]
    frame_bytes = width * strip_h * 3
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, bufsize=frame_bytes * 8)
    index = 0
    try:
        while True:
            buf = proc.stdout.read(frame_bytes)
            while 0 < len(buf) < frame_bytes:
                more = proc.stdout.read(frame_bytes - len(buf))
                if not more:
                    break
                buf += more
            if len(buf) < frame_bytes:
                break
            strip = np.frombuffer(buf, np.uint8).reshape(strip_h, width, 3)
            yield start + index / fps, strip
            index += 1
    finally:
        proc.stdout.close()
        proc.wait()


def _ocr_available(engine: str = DEFAULT_OCR_ENGINE) -> bool:
    """Whether the selected OCR engine can run (see :mod:`.ocr`)."""
    return engine_available(engine)[0]


def _ocr_deaths(
    kda_bgr: np.ndarray, previous: int, engine: str = DEFAULT_OCR_ENGINE
) -> int:
    """Read the K/D/A deaths (middle) number; keep it monotonic non-decreasing."""
    gray = cv2.cvtColor(kda_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, None, fx=6, fy=6, interpolation=cv2.INTER_CUBIC)
    _, bw = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY_INV)
    text = read_digits(engine, bw)
    nums = re.findall(r"\d+", text)
    if len(nums) < 3:
        return previous
    value = int(nums[1])
    # Accept only a sane non-decreasing step (tolerate a couple of missed reads).
    return value if previous <= value <= previous + 3 else previous


def _ocr_kda(
    kda_bgr: np.ndarray,
    previous: tuple[int, int, int],
    engine: str = DEFAULT_OCR_ENGINE,
) -> tuple[int, int, int]:
    """Read the full kills/deaths/assists triple, kept monotonic non-decreasing.

    Mirrors :func:`_ocr_deaths`'s preprocessing but returns all three counters.
    Each value only ever rises during a match, so a read below the previous value
    (or an implausible jump of more than a couple) is rejected as OCR noise and
    the previous value carried forward.

    Args:
        kda_bgr: The K/D/A box crop (BGR).
        previous: The last accepted ``(kills, deaths, assists)`` triple.
        engine: The OCR engine to read with (see :mod:`.ocr`).

    Returns:
        The updated ``(kills, deaths, assists)`` triple.
    """
    gray = cv2.cvtColor(kda_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, None, fx=6, fy=6, interpolation=cv2.INTER_CUBIC)
    _, bw = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY_INV)
    text = read_digits(engine, bw)
    nums = re.findall(r"\d+", text)
    if len(nums) < 3:
        return previous
    updated = []
    for value_str, prev in zip(nums[:3], previous):
        value = int(value_str)
        updated.append(value if prev <= value <= prev + 3 else prev)
    return updated[0], updated[1], updated[2]


def _respawn_signal(strip: np.ndarray, center: int, layout: DotaHudLayout) -> float:
    """Fraction of golden pixels in the respawn-box region under the slot.

    The respawn countdown box has a distinctive gold border that is present only
    while the player is dead, so this fraction spikes during a death and is ~0
    otherwise.
    """
    x0, y0, x1, y1 = layout.respawn_box(center)
    crop = strip[y0:y1, x0:x1]
    if crop.size == 0:
        return 0.0
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    gold = (
        (h >= _GOLD_H_LO)
        & (h <= _GOLD_H_HI)
        & (s > _GOLD_MIN_SAT)
        & (v > _GOLD_MIN_VAL)
    )
    return float(gold.mean())


def _signal_runs(
    times: list[float], signal: list[float], threshold: float, min_samples: int
) -> list[dict]:
    """Contiguous runs where ``signal`` exceeds ``threshold`` (dead)."""
    runs: list[dict] = []
    start = None
    for i, value in enumerate(signal):
        if value > threshold and start is None:
            start = i
        elif value <= threshold and start is not None:
            if i - start >= min_samples:
                runs.append(
                    {
                        "start": times[start],
                        "end": times[i - 1]
                        + (times[1] - times[0] if len(times) > 1 else 1.0),
                    }
                )
            start = None
    if start is not None and len(signal) - start >= min_samples:
        step = times[1] - times[0] if len(times) > 1 else 1.0
        runs.append({"start": times[start], "end": times[-1] + step})
    return runs


def _dead_state_runs(
    times: list[float],
    signal: list[float],
    *,
    threshold: float,
    enter_samples: int,
    exit_samples: int,
    stream_end: float | None = None,
) -> list[dict]:
    """Return persistent dead-state runs while bridging brief timer dropouts.

    Boundaries are the first samples of the confirmed transitions, not the
    later samples that complete the persistence check. No minimum duration is
    applied, so a quick buyback remains a valid interval.
    """
    if not times or len(times) != len(signal):
        return []
    enter_samples = max(1, int(enter_samples))
    exit_samples = max(1, int(exit_samples))
    runs: list[dict] = []
    dead = False
    start_time: float | None = None
    enter_start: int | None = None
    exit_start: int | None = None

    for index, value in enumerate(signal):
        is_dead = value > threshold
        if not dead:
            if is_dead:
                if enter_start is None:
                    enter_start = index
                if index - enter_start + 1 >= enter_samples:
                    dead = True
                    start_time = times[enter_start]
                    enter_start = None
            else:
                enter_start = None
            continue

        if is_dead:
            exit_start = None
            continue
        if exit_start is None:
            exit_start = index
        if index - exit_start + 1 >= exit_samples:
            runs.append({"start": start_time, "end": times[exit_start]})
            dead = False
            start_time = None
            exit_start = None

    if dead and start_time is not None:
        # Reaching EOF before ``exit_samples`` alive samples means the apparent
        # exit is unconfirmed and may only be a timer-rendering dropout. Keep
        # the dead interval through the final sample; a confirmed respawn or
        # buyback has already taken the branch above and set ``dead`` false.
        if stream_end is not None and stream_end > 0:
            end_time = float(stream_end)
        else:
            step = times[1] - times[0] if len(times) > 1 else 1.0
            end_time = times[-1] + step
        runs.append({"start": start_time, "end": end_time})
    return runs


def _stable_transition_time(
    times: list[float],
    signal: list[float],
    *,
    target_dead: bool,
    threshold: float,
    stable_samples: int,
) -> float | None:
    """Find the first frame of a persistent alive/dead transition.

    The opposite state must appear earlier in the window. This prevents a
    refinement window that starts after the transition from inventing a new
    boundary at the window edge.
    """
    if len(times) != len(signal):
        return None
    stable_samples = max(1, int(stable_samples))
    seen_opposite = False
    candidate: int | None = None
    for index, value in enumerate(signal):
        is_dead = value > threshold
        if is_dead != target_dead:
            seen_opposite = True
            candidate = None
            continue
        if not seen_opposite:
            continue
        if candidate is None:
            candidate = index
        if index - candidate + 1 >= stable_samples:
            return times[candidate]
    return None


def _refine_dead_interval(
    coarse: dict,
    start_times: list[float],
    start_signal: list[float],
    end_times: list[float],
    end_signal: list[float],
    *,
    threshold: float,
    stable_samples: int,
) -> dict:
    """Refine a coarse timer run, falling back per unreadable transition."""
    start = _stable_transition_time(
        start_times,
        start_signal,
        target_dead=True,
        threshold=threshold,
        stable_samples=stable_samples,
    )
    end = _stable_transition_time(
        end_times,
        end_signal,
        target_dead=False,
        threshold=threshold,
        stable_samples=stable_samples,
    )
    refined_start = float(coarse["start"]) if start is None else start
    refined_end = float(coarse["end"]) if end is None else end
    if refined_end <= refined_start:
        return {"start": float(coarse["start"]), "end": float(coarse["end"])}
    return {"start": refined_start, "end": refined_end}


def _respawn_window_samples(
    video_path: str | Path,
    start: float,
    end: float,
    *,
    fps: float,
    width: int,
    layout: DotaHudLayout,
    slot_center: int,
) -> tuple[list[float], list[float]]:
    """Decode one short HUD window and return timer-signal samples."""
    times: list[float] = []
    signal: list[float] = []
    for timestamp, strip in _stream_top_strip_window(
        video_path,
        start,
        end,
        fps,
        width,
        layout.strip_height,
    ):
        times.append(timestamp)
        signal.append(_respawn_signal(strip, slot_center, layout))
    return times, signal


def _refine_video_dead_interval(
    video_path: str | Path,
    coarse: dict,
    *,
    width: int,
    layout: DotaHudLayout,
    slot_center: int,
    preserve_end: bool = False,
) -> dict:
    """Re-decode small windows around a coarse dead interval's boundaries."""
    start_times, start_signal = _respawn_window_samples(
        video_path,
        coarse["start"] - _REFINE_WINDOW_SECONDS,
        coarse["start"] + _REFINE_WINDOW_SECONDS,
        fps=_REFINE_FPS,
        width=width,
        layout=layout,
        slot_center=slot_center,
    )
    end_times: list[float] = []
    end_signal: list[float] = []
    if not preserve_end:
        end_times, end_signal = _respawn_window_samples(
            video_path,
            coarse["end"] - _REFINE_WINDOW_SECONDS,
            coarse["end"] + _REFINE_WINDOW_SECONDS,
            fps=_REFINE_FPS,
            width=width,
            layout=layout,
            slot_center=slot_center,
        )
    return _refine_dead_interval(
        coarse,
        start_times,
        start_signal,
        end_times,
        end_signal,
        threshold=_GOLD_FRACTION,
        stable_samples=_REFINE_STABLE_SAMPLES,
    )


def _coarse_runs_with_refined_boundaries(
    video_path: str | Path,
    times: list[float],
    signal: list[float],
    *,
    width: int,
    layout: DotaHudLayout,
    slot_center: int,
    stream_end: float | None = None,
) -> list[dict]:
    """Build persistent coarse runs and refine every start/end transition."""
    runs = _dead_state_runs(
        times,
        signal,
        threshold=_GOLD_FRACTION,
        enter_samples=_COARSE_ENTER_SAMPLES,
        exit_samples=_COARSE_EXIT_SAMPLES,
        stream_end=stream_end,
    )
    exit_confirmed = len(signal) >= _COARSE_EXIT_SAMPLES and all(
        value <= _GOLD_FRACTION for value in signal[-_COARSE_EXIT_SAMPLES:]
    )
    refined: list[dict] = []
    for index, run in enumerate(runs):
        refined.append(
            _refine_video_dead_interval(
                video_path,
                run,
                width=width,
                layout=layout,
                slot_center=slot_center,
                preserve_end=index == len(runs) - 1 and not exit_confirmed,
            )
        )
    return refined


def _death_event_times(deaths_series: list[int], times: list[float]) -> list[float]:
    """Timestamps where the deaths counter increments."""
    events = []
    prev = deaths_series[0] if deaths_series else 0
    for t, d in zip(times[1:], deaths_series[1:]):
        if d > prev:
            events.append(t)
        prev = d
    return events


def _death_intervals_from_runs(
    runs: list[dict], death_times: list[float]
) -> list[dict]:
    """Dead windows for cutting: OCR death moment as start, respawn box as end.

    Each golden respawn-box run is a confirmed dead window with a reliable *end*.
    When the K/D/A deaths counter was OCR'd, the exact moment of death is the
    increment timestamp, so each run's *start* is replaced by the nearest deaths
    increment within :data:`_DEATH_MATCH_WINDOW` (kept strictly before the run's
    end). Runs with no matching increment keep their respawn-box start, so a
    death the OCR missed is still cut. Each increment is consumed at most once.

    Args:
        runs: Golden respawn-box runs, each ``{"start", "end"}`` in seconds.
        death_times: OCR deaths-counter increment timestamps (empty when OCR
            did not run), in time order.

    Returns:
        list[dict]: ``{"start", "end"}`` dead windows in the order of ``runs``.
    """
    remaining = sorted(death_times)
    intervals: list[dict] = []
    for run in runs:
        start = run["start"]
        best_idx, best_dt = None, _DEATH_MATCH_WINDOW
        for i, t in enumerate(remaining):
            dt = abs(t - run["start"])
            if dt <= best_dt:
                best_idx, best_dt = i, dt
        if best_idx is not None:
            matched = remaining.pop(best_idx)
            if matched < run["end"]:
                start = matched
        intervals.append({"start": start, "end": run["end"]})
    return intervals


def detect_death_intervals(
    video_path: str | Path,
    fps: float = _COARSE_FPS,
    team: str = "radiant",
    player_slot: int | None = None,
    use_ocr: bool = False,
    ocr_engine: str = DEFAULT_OCR_ENGINE,
    layout: DotaHudLayout | None = None,
) -> list[dict]:
    """Detect the player's dead intervals in a Dota 2 recording.

    The primary signal is the golden respawn-countdown box under the player's
    fixed top-bar slot: it is present only while dead, so its runs are the dead
    windows directly (and it ends early on buyback/Aegis). Runs shorter than
    :data:`_MIN_DEATH_SECONDS` are treated as UI noise. The K/D/A OCR is optional
    corroboration only — over a full match it is too noisy to anchor timings.

    Args:
        video_path: The gameplay recording (HUD visible).
        fps: Coarse sampling rate in frames per second. Candidate boundaries
            are automatically re-decoded at a higher frame rate.
        team: The player's team (``"radiant"`` or ``"dire"``).
        player_slot: 0-based top-bar slot of the player; auto-identified via
            :func:`identify_player_slot` when ``None``.
        use_ocr: When ``True`` and the OCR engine is available, tag each interval
            with ``"confirmed"`` if a K/D/A deaths increment lands near its start.
        ocr_engine: Which OCR engine reads the counter (see :mod:`.ocr`).
        layout: HUD geometry; defaults to the calibrated layout for the video's
            resolution.

    Returns:
        list[dict]: Dead intervals ``{"start", "end", "duration"}`` in source
        seconds, in time order (plus ``"confirmed"`` when ``use_ocr``).

    Raises:
        FileNotFoundError: If ``video_path`` does not exist.
        RuntimeError: If the player's slot cannot be identified.
    """
    video_path = Path(video_path)
    if not video_path.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")

    width, height, duration = _video_metadata(video_path)
    layout = (layout or DotaHudLayout()).scaled(width, height)
    centers = layout.team_centers(team)

    if player_slot is None:
        player_slot, confidence = identify_player_slot(video_path, layout, team)
        logger.info(
            "Identified player slot %d (confidence %.2f)", player_slot, confidence
        )
    slot_center = centers[player_slot]

    ocr_on = use_ocr and _ocr_available(ocr_engine)
    if use_ocr and not ocr_on:
        logger.warning(
            "OCR engine %r unavailable; skipping K/D/A confirmation", ocr_engine
        )

    times: list[float] = []
    respawn: list[float] = []
    deaths_series: list[int] = []
    deaths = 0
    for t, strip in _stream_top_strip(video_path, fps, width, layout.strip_height):
        times.append(t)
        respawn.append(_respawn_signal(strip, slot_center, layout))
        if ocr_on:
            deaths = _ocr_deaths(_crop(strip, layout.kda_box), deaths, ocr_engine)
            deaths_series.append(deaths)

    if not times:
        return []

    intervals = _coarse_runs_with_refined_boundaries(
        video_path,
        times,
        respawn,
        width=width,
        layout=layout,
        slot_center=slot_center,
        stream_end=duration,
    )

    events = _death_event_times(deaths_series, times) if ocr_on else []
    for run in intervals:
        if ocr_on:
            run["confirmed"] = any(
                abs(e - run["start"]) <= _DEATH_MATCH_WINDOW for e in events
            )
        run["duration"] = round(run["end"] - run["start"], 2)
        run["start"] = round(run["start"], 2)
        run["end"] = round(run["end"], 2)
    return intervals


def detect_gaming_markers(
    video_path: str | Path,
    fps: float = _COARSE_FPS,
    team: str = "radiant",
    player_slot: int | None = None,
    detect_kda: bool = True,
    ocr_engine: str = DEFAULT_OCR_ENGINE,
    layout: DotaHudLayout | None = None,
) -> dict:
    """Single-pass detection of dead intervals plus K/D/A timeline markers.

    Runs one HUD scan and derives two things from it. When ``detect_kda`` is set
    and the OCR engine is available, all three K/D/A markers come from the
    top-left counter's increments — kills, deaths *and* assists — and each dead
    interval starts at its deaths-counter increment (the exact moment of death)
    while its end still comes from the reliable golden respawn-box run
    (:func:`_death_intervals_from_runs`). Without OCR (``detect_kda`` off or the
    engine missing) the respawn box alone drives both the intervals and the
    ``"D"`` markers, exactly as :func:`detect_death_intervals`.

    Args:
        video_path: The gameplay recording (HUD visible).
        fps: Sampling rate in frames per second.
        team: The player's team (``"radiant"`` or ``"dire"``).
        player_slot: 0-based top-bar slot; auto-identified when ``None``.
        detect_kda: When ``True`` and the OCR engine is available, emit K/D/A
            markers from the OCR'd counter and anchor each interval's start on
            its deaths increment.
        ocr_engine: Which OCR engine reads the counter (see :mod:`.ocr`).
        layout: HUD geometry; defaults to the calibrated layout for the video.

    Returns:
        dict: ``{"player_slot", "confidence", "intervals", "events"}`` where
        ``confidence`` is ``None`` if the caller supplied ``player_slot``,
        ``intervals`` are ``{"start", "end", "duration"}`` dead windows, and
        ``events`` are time-sorted ``{"time", "kind"}`` markers with ``kind`` in
        ``{"K", "D", "A"}``.

    Raises:
        FileNotFoundError: If ``video_path`` does not exist.
        RuntimeError: If the player's slot cannot be identified.
    """
    video_path = Path(video_path)
    if not video_path.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")

    width, height, duration = _video_metadata(video_path)
    layout = (layout or DotaHudLayout()).scaled(width, height)
    centers = layout.team_centers(team)

    confidence: float | None = None
    if player_slot is None:
        player_slot, confidence = identify_player_slot(video_path, layout, team)
        logger.info(
            "Identified player slot %d (confidence %.2f)", player_slot, confidence
        )
    slot_center = centers[player_slot]

    kda_on = detect_kda and _ocr_available(ocr_engine)
    if detect_kda and not kda_on:
        logger.warning("OCR engine %r unavailable; skipping K/D/A markers", ocr_engine)

    times: list[float] = []
    respawn: list[float] = []
    kills_series: list[int] = []
    deaths_series: list[int] = []
    assists_series: list[int] = []
    kda = (0, 0, 0)
    for t, strip in _stream_top_strip(video_path, fps, width, layout.strip_height):
        times.append(t)
        respawn.append(_respawn_signal(strip, slot_center, layout))
        if kda_on:
            kda = _ocr_kda(_crop(strip, layout.kda_box), kda, ocr_engine)
            kills_series.append(kda[0])
            deaths_series.append(kda[1])
            assists_series.append(kda[2])

    if not times:
        return {
            "player_slot": player_slot,
            "confidence": confidence,
            "intervals": [],
            "events": [],
            "kda_available": kda_on,
        }

    # The selected top portrait's timer is authoritative for both boundaries.
    # OCR remains a separate source of K/D/A markers and never moves a cut.
    intervals = _coarse_runs_with_refined_boundaries(
        video_path,
        times,
        respawn,
        width=width,
        layout=layout,
        slot_center=slot_center,
        stream_end=duration,
    )
    death_times = _death_event_times(deaths_series, times) if kda_on else []
    for run in intervals:
        run["duration"] = round(run["end"] - run["start"], 2)
        run["start"] = round(run["start"], 2)
        run["end"] = round(run["end"], 2)

    # K/D/A markers all come from the OCR'd counter; without OCR the only signal
    # is the respawn box, so deaths fall back to the interval starts.
    if kda_on:
        events: list[dict] = []
        for t in _death_event_times(kills_series, times):
            events.append({"time": round(t, 2), "kind": "K"})
        for t in death_times:
            events.append({"time": round(t, 2), "kind": "D"})
        for t in _death_event_times(assists_series, times):
            events.append({"time": round(t, 2), "kind": "A"})
    else:
        events = [{"time": run["start"], "kind": "D"} for run in intervals]
    events.sort(key=lambda e: e["time"])

    return {
        "player_slot": player_slot,
        "confidence": confidence,
        "intervals": intervals,
        "events": events,
        "kda_available": kda_on,
    }
