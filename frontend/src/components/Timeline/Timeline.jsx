import { useEffect, useMemo, useRef, useState } from 'react';
import { formatTime } from '../../utils/timeFormat';
import styles from './Timeline.module.css';

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
  onSeek,
  onSplitAtPlayhead,
  onReorder,
  onDeleteSegment,
  onReset,
  onSave,
}) {
  const [selectedId, setSelectedId] = useState(null);
  const [dragIndex, setDragIndex] = useState(null);
  const [dropIndex, setDropIndex] = useState(null);
  const trackRef = useRef(null);

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

  const ticks = useMemo(() => {
    if (totalDuration <= 0) return [];
    const interval = pickTickInterval(totalDuration);
    const result = [];
    for (let t = 0; t <= totalDuration; t += interval) {
      result.push(t);
    }
    return result;
  }, [totalDuration]);

  const timelineToSource = (timelineTime) => {
    for (let i = 0; i < segments.length; i += 1) {
      const length = segments[i].end - segments[i].start;
      if (timelineTime < offsets[i] + length) {
        return segments[i].start + (timelineTime - offsets[i]);
      }
    }
    return segments.length ? segments[segments.length - 1].end : 0;
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
    setSelectedId(segment.id);
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

  if (!segments.length || totalDuration <= 0) {
    return null;
  }

  const selectedIndex = segments.findIndex((segment) => segment.id === selectedId);

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
              setSelectedId(null);
            }
          }}
          disabled={selectedIndex === -1 || segments.length <= 1}
        >
          Delete segment
        </button>
        <button type="button" className={styles.toolButton} onClick={onReset}>
          Reset
        </button>

        <span className={styles.summary}>
          {segments.length} segment{segments.length === 1 ? '' : 's'} ·{' '}
          {formatTime(totalDuration)}
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

      <div
        ref={trackRef}
        className={styles.track}
        onDrop={handleDrop}
        onDragOver={(event) => {
          if (dragIndex !== null) event.preventDefault();
        }}
      >
        {segments.map((segment, index) => {
          const length = segment.end - segment.start;
          const isSelected = segment.id === selectedId;
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
                    setSelectedId(null);
                  }}
                >
                  ✕
                </button>
              )}
            </div>
          );
        })}

        {playheadTime !== null && (
          <div
            className={styles.playhead}
            style={{ left: `${(playheadTime / totalDuration) * 100}%` }}
          />
        )}
      </div>

      <p className={styles.hintRow}>
        Click a segment to select and seek · drag segments to rearrange · the
        rendered video follows this order
      </p>
    </div>
  );
}

export default Timeline;
