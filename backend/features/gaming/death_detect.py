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
# A golden run must span at least this many samples to start one.
_MIN_RESPAWN_SAMPLES = 2
# Real deaths keep you dead at least this long as one *continuous* run; shorter
# golden blips (and intermittent flicker) are UI noise. Runs are deliberately
# not merged across gaps — a solid respawn box never flickers, so a gap means
# two separate events, not one. (An ultra-short early respawn isn't worth
# cutting anyway.)
_MIN_DEATH_SECONDS = 5.0
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
    # Dire (right-of-score) slot centres are not yet calibrated on sample
    # footage; radiant is the validated default.
    dire_centers: tuple[int, ...] = ()

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
    from moviepy import VideoFileClip

    clip = VideoFileClip(str(video_path))
    try:
        return int(clip.w), int(clip.h)
    finally:
        clip.close()


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
        sample_times: Seconds to sample; defaults to a spread across the early
            game.

    Returns:
        tuple[int, float]: ``(slot_index, confidence)`` — the 0-based slot and a
        vote-share confidence in ``[0, 1]``. Confidence 0 means no confident vote.
    """
    width, height = _video_dimensions(video_path)
    layout = (layout or DotaHudLayout()).scaled(width, height)
    centers = layout.team_centers(team)
    if sample_times is None:
        sample_times = [float(t) for t in range(40, 200, 12)]

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
        sample_time: Frame time to cut the thumbnails from; defaults to an early
            in-game moment where portraits are clearly visible.

    Returns:
        tuple[int, float, list[np.ndarray]]: ``(auto_slot, confidence, thumbs)``
        where ``thumbs`` are BGR crops of the five team portraits in slot order.
    """
    width, height = _video_dimensions(video_path)
    layout = (layout or DotaHudLayout()).scaled(width, height)
    centers = layout.team_centers(team)

    try:
        auto_slot, confidence = identify_player_slot(video_path, layout, team)
    except RuntimeError:
        auto_slot, confidence = -1, 0.0

    if sample_time is None:
        sample_time = 90.0
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


def _ocr_available() -> bool:
    try:
        import pytesseract

        pytesseract.get_tesseract_version()
        return True
    except Exception:  # noqa: BLE001 - any import/binary failure disables OCR
        return False


def _ocr_deaths(kda_bgr: np.ndarray, previous: int) -> int:
    """Read the K/D/A deaths (middle) number; keep it monotonic non-decreasing."""
    import pytesseract

    gray = cv2.cvtColor(kda_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, None, fx=6, fy=6, interpolation=cv2.INTER_CUBIC)
    _, bw = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY_INV)
    text = pytesseract.image_to_string(
        bw, config="--psm 7 -c tessedit_char_whitelist=0123456789/"
    )
    nums = re.findall(r"\d+", text)
    if len(nums) < 3:
        return previous
    value = int(nums[1])
    # Accept only a sane non-decreasing step (tolerate a couple of missed reads).
    return value if previous <= value <= previous + 3 else previous


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


def _death_event_times(deaths_series: list[int], times: list[float]) -> list[float]:
    """Timestamps where the deaths counter increments."""
    events = []
    prev = deaths_series[0] if deaths_series else 0
    for t, d in zip(times[1:], deaths_series[1:]):
        if d > prev:
            events.append(t)
        prev = d
    return events


def detect_death_intervals(
    video_path: str | Path,
    fps: float = 1.0,
    team: str = "radiant",
    player_slot: int | None = None,
    use_ocr: bool = False,
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
        fps: Sampling rate in frames per second (1.0 is ample; deaths last
            several seconds).
        team: The player's team (``"radiant"`` or ``"dire"``).
        player_slot: 0-based top-bar slot of the player; auto-identified via
            :func:`identify_player_slot` when ``None``.
        use_ocr: When ``True`` and tesseract is available, tag each interval with
            ``"confirmed"`` if a K/D/A deaths increment lands near its start.
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

    width, height = _video_dimensions(video_path)
    layout = (layout or DotaHudLayout()).scaled(width, height)
    centers = layout.team_centers(team)

    if player_slot is None:
        player_slot, confidence = identify_player_slot(video_path, layout, team)
        logger.info(
            "Identified player slot %d (confidence %.2f)", player_slot, confidence
        )
    slot_center = centers[player_slot]

    ocr_on = use_ocr and _ocr_available()
    if use_ocr and not ocr_on:
        logger.warning("tesseract unavailable; skipping K/D/A confirmation")

    times: list[float] = []
    respawn: list[float] = []
    deaths_series: list[int] = []
    deaths = 0
    for t, strip in _stream_top_strip(video_path, fps, width, layout.strip_height):
        times.append(t)
        respawn.append(_respawn_signal(strip, slot_center, layout))
        if ocr_on:
            deaths = _ocr_deaths(_crop(strip, layout.kda_box), deaths)
            deaths_series.append(deaths)

    if not times:
        return []

    # Golden respawn-box runs are the dead windows; keep solid runs, drop noise.
    runs = _signal_runs(times, respawn, _GOLD_FRACTION, _MIN_RESPAWN_SAMPLES)
    intervals = [r for r in runs if r["end"] - r["start"] >= _MIN_DEATH_SECONDS]

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
