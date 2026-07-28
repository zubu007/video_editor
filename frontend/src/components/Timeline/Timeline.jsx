import { useMemo, useRef, useState, useEffect } from 'react';
import { formatTime } from '../../utils/timeFormat';
import styles from './Timeline.module.css';

// Overlay lanes stacked above the base video track. Each lane holds edit
// operations of one type; clips are positioned in timeline time but stored
// in source time (matching how the backend renders them).
const OVERLAY_LANES = [
  { type: 'zoom', label: 'Zoom', clipClass: 'zoomClip' },
  { type: 'insert_stock_footage', label: 'B-roll', clipClass: 'stockClip' },
  { type: 'diagram', label: 'Diagram', clipClass: 'diagramClip' },
];

const MIN_OVERLAY_LENGTH = 0.2;

// Horizontal zoom steps. 1 = the whole timeline fits the visible width; at
// higher factors the lane content overflows and the track scrolls sideways.
const ZOOM_LEVELS = [1, 1.5, 2, 3, 4, 6, 8, 12, 16, 24, 32];

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function overlayLabel(overlay) {
  const meta = overlay.metadata || {};
  if (overlay.type === 'zoom') {
    return `Zoom ×${meta.zoom_level ?? 1.2}`;
  }
  if (overlay.type === 'insert_stock_footage') {
    return meta.search_query || 'B-roll';
  }
  return meta.title || meta.diagram_type || 'Diagram';
}

function pickTickInterval(totalSeconds) {
  const intervals = [0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600];
  const ideal = totalSeconds / 10;
  return intervals.find((interval) => interval >= ideal) || 600;
}

function SegmentWaveform({ waveformData, duration, start, end }) {
  const canvasRef = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !waveformData?.length || !duration) return undefined;

    const draw = () => {
      const rect = canvas.parentElement.getBoundingClientRect();
      if (rect.width === 0 || rect.height === 0) return;
      const dpr = window.devicePixelRatio || 1;
      canvas.width = rect.width * dpr;
      canvas.height = rect.height * dpr;
      const ctx = canvas.getContext('2d');
      ctx.scale(dpr, dpr);
      ctx.clearRect(0, 0, rect.width, rect.height);

      const firstPeak = Math.floor((start / duration) * waveformData.length);
      const lastPeak = Math.ceil((end / duration) * waveformData.length);
      const peaks = waveformData.slice(firstPeak, Math.max(lastPeak, firstPeak + 1));
      if (peaks.length === 0) return;

      const barWidth = rect.width / peaks.length;
      const centerY = rect.height / 2;
      ctx.fillStyle = 'rgba(59, 130, 246, 0.55)';
      peaks.forEach((amplitude, index) => {
        const barHeight = Math.max(amplitude * rect.height * 0.85, 1);
        ctx.fillRect(
          index * barWidth,
          centerY - barHeight / 2,
          Math.max(barWidth - 0.5, 0.5),
          barHeight
        );
      });
    };

    draw();
    const observer = new ResizeObserver(draw);
    observer.observe(canvas.parentElement);
    return () => observer.disconnect();
  }, [waveformData, duration, start, end]);

  return <canvas ref={canvasRef} className={styles.segmentCanvas} />;
}

function Timeline({
  segments,
  duration,
  waveformData,
  currentTime,
  isDirty,
  isSaving,
  overlays = [],
  selectedSegmentId = null,
  selectedOverlayId = null,
  onSeek,
  onSplitAtPlayhead,
  onReorder,
  onDeleteSegment,
  onReset,
  onSave,
  onAddOverlay,
  onUpdateOverlay,
  onDeleteOverlay,
  onSelectSegment,
  onSelectOverlay,
}) {
  const [dragIndex, setDragIndex] = useState(null);
  const [dropIndex, setDropIndex] = useState(null);
  // In-flight drag values for one overlay, applied over its stored values so
  // the clip follows the pointer before the change is persisted.
  const [overlayDraft, setOverlayDraft] = useState(null);
  const [zoom, setZoom] = useState(1);
  const lanesRef = useRef(null);
  const scrollerRef = useRef(null);
  // Timeline-time to re-centre on after a zoom change, applied once the new
  // content width has been laid out.
  const zoomAnchorRef = useRef(null);

  const totalDuration = useMemo(
    () => segments.reduce((sum, segment) => sum + (segment.end - segment.start), 0),
    [segments]
  );

  // Cumulative timeline-time offset at which each segment starts.
  const offsets = useMemo(() => {
    const result = [];
    let acc = 0;
    segments.forEach((segment) => {
      result.push(acc);
      acc += segment.end - segment.start;
    });
    return result;
  }, [segments]);

  // Timeline-time position of the playhead, or null when the current source
  // time falls outside every segment (e.g. inside a deleted range).
  const playheadTime = useMemo(() => {
    for (let i = 0; i < segments.length; i += 1) {
      const segment = segments[i];
      if (currentTime >= segment.start && currentTime < segment.end) {
        return offsets[i] + (currentTime - segment.start);
      }
    }
    return null;
  }, [segments, offsets, currentTime]);

  // Tick density follows the zoom: the visible window is totalDuration / zoom
  // seconds wide, so ticks stay roughly evenly spaced on screen.
  const ticks = useMemo(() => {
    if (totalDuration <= 0) return [];
    const interval = pickTickInterval(totalDuration / zoom);
    const result = [];
    for (let t = 0; t <= totalDuration; t += interval) {
      result.push(t);
    }
    return result;
  }, [totalDuration, zoom]);

  // Scroll so `timelineTime` sits in the middle of the visible window.
  const centerOn = (timelineTime) => {
    const scroller = scrollerRef.current;
    if (!scroller || totalDuration <= 0) return;
    const viewport = scroller.clientWidth;
    const contentWidth = viewport * zoom;
    const x = (timelineTime / totalDuration) * contentWidth;
    scroller.scrollLeft = clamp(x - viewport / 2, 0, Math.max(contentWidth - viewport, 0));
  };

  const changeZoom = (direction) => {
    const index = ZOOM_LEVELS.indexOf(zoom);
    const nextIndex = clamp(
      (index === -1 ? 0 : index) + direction,
      0,
      ZOOM_LEVELS.length - 1
    );
    if (ZOOM_LEVELS[nextIndex] === zoom) return;

    const scroller = scrollerRef.current;
    if (scroller && totalDuration > 0) {
      // Keep the playhead put when it is on screen, otherwise the time
      // currently in the middle of the window.
      const viewport = scroller.clientWidth;
      const centerTime =
        ((scroller.scrollLeft + viewport / 2) / (viewport * zoom)) * totalDuration;
      zoomAnchorRef.current = playheadTime ?? centerTime;
    }
    setZoom(ZOOM_LEVELS[nextIndex]);
  };

  // Re-centre after the zoomed lanes have been laid out at their new width.
  useEffect(() => {
    if (zoomAnchorRef.current === null) return;
    centerOn(zoomAnchorRef.current);
    zoomAnchorRef.current = null;
  }, [zoom]); // eslint-disable-line react-hooks/exhaustive-deps

  // Follow the playhead while it plays past the edge of the visible window.
  useEffect(() => {
    const scroller = scrollerRef.current;
    if (!scroller || zoom <= 1 || playheadTime === null || totalDuration <= 0) {
      return;
    }
    const viewport = scroller.clientWidth;
    const x = (playheadTime / totalDuration) * viewport * zoom;
    const margin = viewport * 0.1;
    if (x < scroller.scrollLeft + margin || x > scroller.scrollLeft + viewport - margin) {
      centerOn(playheadTime);
    }
  }, [playheadTime, zoom, totalDuration]); // eslint-disable-line react-hooks/exhaustive-deps

  const timelineToSource = (timelineTime) => {
    for (let i = 0; i < segments.length; i += 1) {
      const length = segments[i].end - segments[i].start;
      if (timelineTime < offsets[i] + length) {
        return segments[i].start + (timelineTime - offsets[i]);
      }
    }
    return segments.length ? segments[segments.length - 1].end : 0;
  };

  // Map a source-time range onto the timeline: one piece per segment the
  // range intersects. Reordered or deleted segments can split an overlay
  // into several visible pieces (or hide it entirely).
  const overlayPieces = (start, end) => {
    const pieces = [];
    segments.forEach((segment, index) => {
      const pieceStart = Math.max(start, segment.start);
      const pieceEnd = Math.min(end, segment.end);
      if (pieceEnd > pieceStart) {
        pieces.push({
          tStart: offsets[index] + (pieceStart - segment.start),
          tEnd: offsets[index] + (pieceEnd - segment.start),
        });
      }
    });
    return pieces.sort((a, b) => a.tStart - b.tStart);
  };

  const handleRulerClick = (event) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const fraction = Math.max(
      0,
      Math.min(1, (event.clientX - rect.left) / rect.width)
    );
    onSeek(timelineToSource(fraction * totalDuration));
  };

  const handleSegmentClick = (event, segment) => {
    onSelectSegment?.(segment.id);
    const rect = event.currentTarget.getBoundingClientRect();
    const fraction = Math.max(
      0,
      Math.min(1, (event.clientX - rect.left) / rect.width)
    );
    onSeek(segment.start + fraction * (segment.end - segment.start));
  };

  const handleDragStart = (event, index) => {
    setDragIndex(index);
    event.dataTransfer.effectAllowed = 'move';
    // Firefox requires data for a drag to start.
    event.dataTransfer.setData('text/plain', String(index));
  };

  const handleDragOver = (event, index) => {
    if (dragIndex === null) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = 'move';
    const rect = event.currentTarget.getBoundingClientRect();
    const before = event.clientX - rect.left < rect.width / 2;
    setDropIndex(before ? index : index + 1);
  };

  const handleDrop = (event) => {
    event.preventDefault();
    if (dragIndex !== null && dropIndex !== null) {
      onReorder(dragIndex, dropIndex);
    }
    setDragIndex(null);
    setDropIndex(null);
  };

  const handleDragEnd = () => {
    setDragIndex(null);
    setDropIndex(null);
  };

  // Pointer-based drag for overlay clips: 'move' shifts the whole clip,
  // 'trim-start' / 'trim-end' drag one edge. Positions are tracked in
  // timeline time and converted back to source time for storage.
  const beginOverlayDrag = (event, overlay, mode) => {
    if (event.button !== 0 || !onUpdateOverlay) return;
    const lanes = lanesRef.current;
    if (!lanes || totalDuration <= 0) return;
    const pieces = overlayPieces(overlay.start, overlay.end);
    if (pieces.length === 0) return;

    event.preventDefault();
    event.stopPropagation();
    onSelectOverlay?.(overlay.id);

    const laneWidth = lanes.getBoundingClientRect().width;
    const originX = event.clientX;
    const tStart = pieces[0].tStart;
    const tEnd = pieces[pieces.length - 1].tEnd;
    const length = overlay.end - overlay.start;
    let latest = null;
    let moved = false;

    const handleMove = (moveEvent) => {
      if (Math.abs(moveEvent.clientX - originX) > 2) moved = true;
      if (!moved) return;
      const dxSeconds = ((moveEvent.clientX - originX) / laneWidth) * totalDuration;

      let start = overlay.start;
      let end = overlay.end;
      if (mode === 'move') {
        const maxTStart = Math.max(totalDuration - (tEnd - tStart), 0);
        start = timelineToSource(clamp(tStart + dxSeconds, 0, maxTStart));
        end = start + length;
        if (end > duration) {
          end = duration;
          start = Math.max(0, end - length);
        }
      } else if (mode === 'trim-start') {
        start = timelineToSource(clamp(tStart + dxSeconds, 0, totalDuration));
        start = clamp(start, 0, overlay.end - MIN_OVERLAY_LENGTH);
      } else {
        end = timelineToSource(clamp(tEnd + dxSeconds, 0, totalDuration));
        end = clamp(end, overlay.start + MIN_OVERLAY_LENGTH, duration);
      }

      latest = { id: overlay.id, start, end };
      setOverlayDraft(latest);
    };

    const handleUp = () => {
      window.removeEventListener('pointermove', handleMove);
      window.removeEventListener('pointerup', handleUp);
      if (
        latest &&
        (latest.start !== overlay.start || latest.end !== overlay.end)
      ) {
        onUpdateOverlay(overlay, { start: latest.start, end: latest.end });
      }
      setOverlayDraft(null);
    };

    window.addEventListener('pointermove', handleMove);
    window.addEventListener('pointerup', handleUp);
  };

  if (!segments.length || totalDuration <= 0) {
    return null;
  }

  const selectedIndex = segments.findIndex(
    (segment) => segment.id === selectedSegmentId
  );
  const hiddenOverlayCount = overlays.filter(
    (overlay) => overlayPieces(overlay.start, overlay.end).length === 0
  ).length;

  const renderOverlayClip = (overlay) => {
    const effective =
      overlayDraft && overlayDraft.id === overlay.id
        ? { ...overlay, start: overlayDraft.start, end: overlayDraft.end }
        : overlay;
    const pieces = overlayPieces(effective.start, effective.end);
    if (pieces.length === 0) return null;

    const isSelected = overlay.id === selectedOverlayId;
    const lane = OVERLAY_LANES.find((entry) => entry.type === overlay.type);

    return pieces.map((piece, pieceIndex) => {
      const isFirst = pieceIndex === 0;
      const isLast = pieceIndex === pieces.length - 1;
      const classNames = [styles.overlayClip, styles[lane?.clipClass]];
      if (isSelected) classNames.push(styles.clipSelected);
      if (overlay.enabled === false) classNames.push(styles.clipDisabled);

      return (
        <div
          key={`${overlay.id}-${pieceIndex}`}
          className={classNames.filter(Boolean).join(' ')}
          style={{
            left: `${(piece.tStart / totalDuration) * 100}%`,
            width: `${((piece.tEnd - piece.tStart) / totalDuration) * 100}%`,
          }}
          title={`${overlayLabel(overlay)} · ${formatTime(effective.start)} – ${formatTime(effective.end)}`}
          onPointerDown={(event) => beginOverlayDrag(event, overlay, 'move')}
          onClick={(event) => {
            event.stopPropagation();
            onSelectOverlay?.(overlay.id);
          }}
        >
          {isFirst && (
            <span className={styles.clipLabel}>{overlayLabel(overlay)}</span>
          )}
          {isFirst && (
            <div
              className={`${styles.trimHandle} ${styles.trimStart}`}
              onPointerDown={(event) =>
                beginOverlayDrag(event, overlay, 'trim-start')
              }
            />
          )}
          {isLast && (
            <div
              className={`${styles.trimHandle} ${styles.trimEnd}`}
              onPointerDown={(event) =>
                beginOverlayDrag(event, overlay, 'trim-end')
              }
            />
          )}
          {isSelected && isFirst && onDeleteOverlay && (
            <button
              type="button"
              className={styles.clipDelete}
              aria-label="Delete overlay"
              onPointerDown={(event) => event.stopPropagation()}
              onClick={(event) => {
                event.stopPropagation();
                onDeleteOverlay(overlay);
                onSelectOverlay?.(null);
              }}
            >
              ✕
            </button>
          )}
        </div>
      );
    });
  };

  return (
    <div className={styles.timeline}>
      <div className={styles.toolbar}>
        <button type="button" className={styles.toolButton} onClick={onSplitAtPlayhead}>
          ✂ Split at playhead
        </button>
        <button
          type="button"
          className={styles.toolButton}
          onClick={() => {
            if (selectedIndex !== -1) {
              onDeleteSegment(segments[selectedIndex].id);
              onSelectSegment?.(null);
            }
          }}
          disabled={selectedIndex === -1 || segments.length <= 1}
        >
          Delete segment
        </button>
        <button type="button" className={styles.toolButton} onClick={onReset}>
          Reset
        </button>

        <div className={styles.zoomGroup}>
          <button
            type="button"
            className={styles.zoomButton}
            onClick={() => changeZoom(-1)}
            disabled={zoom === ZOOM_LEVELS[0]}
            title="Zoom out"
            aria-label="Zoom out"
          >
            −
          </button>
          <span className={styles.zoomLabel}>{zoom}×</span>
          <button
            type="button"
            className={styles.zoomButton}
            onClick={() => changeZoom(1)}
            disabled={zoom === ZOOM_LEVELS[ZOOM_LEVELS.length - 1]}
            title="Zoom in"
            aria-label="Zoom in"
          >
            +
          </button>
          <button
            type="button"
            className={styles.toolButton}
            onClick={() => {
              zoomAnchorRef.current = null;
              setZoom(1);
            }}
            disabled={zoom === 1}
            title="Fit the whole timeline"
          >
            Fit
          </button>
        </div>

        <span className={styles.summary}>
          {segments.length} segment{segments.length === 1 ? '' : 's'} ·{' '}
          {formatTime(totalDuration)}
          {overlays.length > 0 && <> · {overlays.length} overlay{overlays.length === 1 ? '' : 's'}</>}
          {isDirty && <span className={styles.dirtyDot} title="Unsaved changes" />}
        </span>

        <button
          type="button"
          className={styles.saveButton}
          onClick={onSave}
          disabled={!isDirty || isSaving}
        >
          {isSaving ? 'Saving…' : 'Save timeline'}
        </button>
      </div>

      <div className={styles.body}>
        <div className={styles.gutter}>
          <div className={styles.gutterRuler} />
          {OVERLAY_LANES.map((lane) => (
            <div key={lane.type} className={styles.gutterLane}>
              <span>{lane.label}</span>
              <button
                type="button"
                className={styles.addButton}
                title={`Add ${lane.label} at playhead`}
                aria-label={`Add ${lane.label} at playhead`}
                disabled={!onAddOverlay}
                onClick={() => onAddOverlay?.(lane.type)}
              >
                +
              </button>
            </div>
          ))}
          <div className={styles.gutterVideo}>
            <span>Video</span>
          </div>
        </div>

        <div className={styles.scroller} ref={scrollerRef}>
          <div
            className={styles.lanes}
            ref={lanesRef}
            style={{ width: `${zoom * 100}%` }}
          >
            <div className={styles.ruler} onClick={handleRulerClick}>
              {ticks.map((tick) => (
                <div
                  key={tick}
                  className={styles.tick}
                  style={{ left: `${(tick / totalDuration) * 100}%` }}
                >
                  <span>{formatTime(tick)}</span>
                </div>
              ))}
            </div>

            {OVERLAY_LANES.map((lane) => (
              <div
                key={lane.type}
                className={styles.overlayLane}
                onClick={() => onSelectOverlay?.(null)}
              >
                {overlays
                  .filter((overlay) => overlay.type === lane.type)
                  .map(renderOverlayClip)}
              </div>
            ))}

            <div
              className={styles.track}
              onDrop={handleDrop}
              onDragOver={(event) => {
                if (dragIndex !== null) event.preventDefault();
              }}
            >
              {segments.map((segment, index) => {
                const length = segment.end - segment.start;
                const isSelected = segment.id === selectedSegmentId;
                const classNames = [styles.segment];
                if (isSelected) classNames.push(styles.selected);
                if (index === dragIndex) classNames.push(styles.dragging);
                if (dropIndex === index) classNames.push(styles.dropBefore);
                if (dropIndex === index + 1 && index === segments.length - 1) {
                  classNames.push(styles.dropAfter);
                }

                return (
                  <div
                    key={segment.id}
                    className={classNames.join(' ')}
                    style={{ width: `${(length / totalDuration) * 100}%` }}
                    draggable
                    onClick={(event) => handleSegmentClick(event, segment)}
                    onDragStart={(event) => handleDragStart(event, index)}
                    onDragOver={(event) => handleDragOver(event, index)}
                    onDragEnd={handleDragEnd}
                    title={`Source ${formatTime(segment.start)} – ${formatTime(segment.end)}`}
                  >
                    <SegmentWaveform
                      waveformData={waveformData}
                      duration={duration}
                      start={segment.start}
                      end={segment.end}
                    />
                    <span className={styles.segmentLabel}>
                      {index + 1} · {formatTime(length)}
                    </span>
                    {isSelected && segments.length > 1 && (
                      <button
                        type="button"
                        className={styles.segmentDelete}
                        aria-label="Delete segment"
                        onClick={(event) => {
                          event.stopPropagation();
                          onDeleteSegment(segment.id);
                          onSelectSegment?.(null);
                        }}
                      >
                        ✕
                      </button>
                    )}
                  </div>
                );
              })}
            </div>

            {playheadTime !== null && (
              <div
                className={styles.playhead}
                style={{ left: `${(playheadTime / totalDuration) * 100}%` }}
              />
            )}
          </div>
        </div>
      </div>

      <p className={styles.hintRow}>
        Click a segment or clip to inspect it below · drag segments to
        rearrange · use the + buttons to add overlays at the playhead · drag
        overlay clips to move, drag their edges to trim · zoom in with + / −
        and scroll the track sideways (shift + wheel)
        {hiddenOverlayCount > 0 && (
          <>
            {' '}· {hiddenOverlayCount} overlay
            {hiddenOverlayCount === 1 ? ' is' : 's are'} outside the current
            segments and hidden
          </>
        )}
      </p>
    </div>
  );
}

export default Timeline;
