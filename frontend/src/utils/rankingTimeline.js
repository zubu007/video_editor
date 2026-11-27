// Mirrors backend/features/ranking/timeline.py and schema framing math. Keep in sync.
export const FPS = 30;
export const CANVAS_WIDTH = 1080;
export const CANVAS_HEIGHT = 1920;
export const PLACEHOLDER_FRAMES = FPS; // one second for slots without media

export function framesFor(trimIn, trimOut) {
  return Math.max(1, Math.floor((trimOut - trimIn) * FPS + 0.5));
}

export function resolvedOut(clip) {
  if (clip.trim_out != null) return clip.trim_out;
  return clip.media ? clip.media.duration : null;
}

export function inPlaybackOrder(clips) {
  return [...clips].sort((a, b) => a.playback_order - b.playback_order);
}

/** Build the half-open frame schedule in playback order. */
export function buildSchedule(clips) {
  let cursor = 0;
  const segments = inPlaybackOrder(clips).map((clip) => {
    const out = resolvedOut(clip);
    const ready = out != null && out - clip.trim_in > 0;
    const frames = ready ? framesFor(clip.trim_in, out) : PLACEHOLDER_FRAMES;
    const segment = {
      clipId: clip.id,
      clip,
      ready,
      startFrame: cursor,
      frames,
    };
    cursor += frames;
    return segment;
  });
  return { segments, totalFrames: cursor, totalSeconds: cursor / FPS };
}

export function segmentIndexAtFrame(schedule, frame) {
  const { segments, totalFrames } = schedule;
  if (!segments.length) return 0;
  const f = Math.max(0, Math.min(frame, totalFrames - 1));
  const index = segments.findIndex(
    (s) => f >= s.startFrame && f < s.startFrame + s.frames
  );
  return index === -1 ? segments.length - 1 : index;
}

/** Ids of clips whose names are visible: everything that started by `frame`. */
export function revealedIdsAt(schedule, frame) {
  const index = segmentIndexAtFrame(schedule, frame);
  return schedule.segments.slice(0, index + 1).map((s) => s.clipId);
}

function evenCeil(value) {
  return Math.max(2, Math.ceil(value / 2) * 2);
}

/** CSS box for the footage inside the viewport; mirrors render._video_filter. */
export function framingBox(clip, viewport) {
  const [, , vw, vh] = viewport;
  const { width: w, height: h } = clip.media;
  if (clip.fit === 'fill') {
    const scale = Math.max(vw / w, vh / h) * clip.zoom;
    const sw = Math.max(evenCeil(w * scale), vw);
    const sh = Math.max(evenCeil(h * scale), vh);
    return {
      width: sw,
      height: sh,
      left: -Math.round((sw - vw) * clip.focal_x),
      top: -Math.round((sh - vh) * clip.focal_y),
    };
  }
  const scale = Math.min(vw / w, vh / h);
  const sw = Math.min(evenCeil(w * scale), vw);
  const sh = Math.min(evenCeil(h * scale), vh);
  return {
    width: sw,
    height: sh,
    left: Math.floor((vw - sw) / 2),
    top: Math.floor((vh - sh) / 2),
  };
}

export function viewportFor(preset) {
  return preset === 'full_frame'
    ? [0, 0, CANVAS_WIDTH, CANVAS_HEIGHT]
    : [0, 220, CANVAS_WIDTH, 1520];
}

// ---- heading text runs ------------------------------------------------------

function runsToChars(runs) {
  return runs.flatMap((run) =>
    [...run.text].map((ch) => ({ ch, color: run.color ?? null }))
  );
}

function charsToRuns(chars) {
  const runs = [];
  chars.forEach(({ ch, color }) => {
    const last = runs[runs.length - 1];
    if (last && last.color === color) last.text += ch;
    else runs.push({ text: ch, color });
  });
  return runs.length ? runs : [{ text: '', color: null }];
}

export function runsText(runs) {
  return runs.map((r) => r.text).join('');
}

/** Apply new plain text, keeping accent colours on unchanged prefix/suffix. */
export function editRunsText(runs, nextText) {
  const before = runsToChars(runs);
  const next = [...nextText];
  let start = 0;
  while (
    start < before.length &&
    start < next.length &&
    before[start].ch === next[start]
  ) {
    start += 1;
  }
  let endB = before.length;
  let endN = next.length;
  while (endB > start && endN > start && before[endB - 1].ch === next[endN - 1]) {
    endB -= 1;
    endN -= 1;
  }
  const inherited = start > 0 ? before[start - 1].color : null;
  const inserted = next.slice(start, endN).map((ch) => ({ ch, color: inherited }));
  return charsToRuns([...before.slice(0, start), ...inserted, ...before.slice(endB)]);
}

/** Colour characters [start, end) with `color` (null clears the accent). */
export function applyAccent(runs, start, end, color) {
  const chars = runsToChars(runs).map((c, i) =>
    i >= start && i < end ? { ...c, color } : c
  );
  return charsToRuns(chars);
}
