import { useEffect, useState } from 'react';
import { formatTime } from '../../utils/timeFormat';
import { getStockFootageURL } from '../../services/api';
import styles from './InspectorPanel.module.css';

const OVERLAY_TYPE_LABELS = {
  zoom: 'Zoom',
  insert_stock_footage: 'B-roll',
  diagram: 'Diagram',
};

const OVERLAY_BADGE_CLASSES = {
  zoom: 'zoomBadge',
  insert_stock_footage: 'stockBadge',
  diagram: 'diagramBadge',
};

const DIAGRAM_TYPES = ['flowchart', 'timeline', 'comparison', 'cycle'];

const MIN_LENGTH = 0.2;

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function round2(value) {
  return Math.round(value * 100) / 100;
}

// Numeric input that keeps a local draft while typing and only commits a
// clamped value on blur/Enter, so keystrokes don't fire a PATCH each.
function NumberField({ label, value, min, max, step = 0.1, onCommit }) {
  const [draft, setDraft] = useState(String(round2(value)));

  useEffect(() => {
    setDraft(String(round2(value)));
  }, [value]);

  const commit = () => {
    const parsed = Number(draft);
    if (Number.isNaN(parsed) || draft.trim() === '') {
      setDraft(String(round2(value)));
      return;
    }
    const next = round2(clamp(parsed, min, max));
    setDraft(String(next));
    if (Math.abs(next - value) > 0.001) {
      onCommit(next);
    }
  };

  return (
    <label className={styles.field}>
      {label}
      <input
        type="number"
        value={draft}
        min={min}
        max={max}
        step={step}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={commit}
        onKeyDown={(event) => {
          if (event.key === 'Enter') event.currentTarget.blur();
        }}
      />
    </label>
  );
}

function SegmentInspector({
  segment,
  index,
  segmentCount,
  sourceDuration,
  onUpdateSegment,
  onDeleteSegment,
}) {
  return (
    <>
      <p className={styles.info}>
        Clip {index + 1} of {segmentCount} · source{' '}
        {formatTime(segment.start)} – {formatTime(segment.end)} ·{' '}
        {formatTime(segment.end - segment.start)} long
      </p>

      <div className={styles.fields}>
        <NumberField
          label="Source start (s)"
          value={segment.start}
          min={0}
          max={segment.end - MIN_LENGTH}
          onCommit={(start) => onUpdateSegment(segment.id, { start })}
        />
        <NumberField
          label="Source end (s)"
          value={segment.end}
          min={segment.start + MIN_LENGTH}
          max={sourceDuration}
          onCommit={(end) => onUpdateSegment(segment.id, { end })}
        />
      </div>

      <div className={styles.actions}>
        <button
          type="button"
          className={styles.dangerButton}
          disabled={segmentCount <= 1}
          onClick={() => onDeleteSegment(segment.id)}
        >
          Delete segment
        </button>
        {segmentCount <= 1 && (
          <span className={styles.note}>The last segment can't be deleted.</span>
        )}
      </div>
    </>
  );
}

function ZoomOptions({ overlay, onUpdateOverlay }) {
  const zoomLevel = Number(overlay.metadata?.zoom_level) || 1.2;
  // Draft while the slider is dragged; committed once on release.
  const [zoomDraft, setZoomDraft] = useState(null);
  const shownZoom = zoomDraft ?? zoomLevel;

  const commitZoom = (value) => {
    setZoomDraft(null);
    const next = round2(clamp(value, 1, 3));
    if (Math.abs(next - zoomLevel) > 0.001) {
      onUpdateOverlay(overlay, {
        metadata: { ...overlay.metadata, zoom_level: next },
      });
    }
  };

  return (
    <div className={styles.fields}>
      <label className={styles.field}>
        Zoom level ×{round2(shownZoom)}
        <input
          type="range"
          min={1}
          max={3}
          step={0.05}
          value={shownZoom}
          onChange={(event) => setZoomDraft(Number(event.target.value))}
          onPointerUp={(event) => commitZoom(Number(event.target.value))}
          onKeyUp={(event) => commitZoom(Number(event.target.value))}
        />
      </label>
      <NumberField
        label="Exact level"
        value={zoomLevel}
        min={1}
        max={3}
        step={0.05}
        onCommit={(value) =>
          onUpdateOverlay(overlay, {
            metadata: { ...overlay.metadata, zoom_level: value },
          })
        }
      />
    </div>
  );
}

function StockOptions({ overlay, stockStatus, onRefetchStock }) {
  const [queryDraft, setQueryDraft] = useState(
    overlay.metadata?.search_query || ''
  );

  useEffect(() => {
    setQueryDraft(overlay.metadata?.search_query || '');
    // Re-seed the draft only when a different clip is inspected.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [overlay.id]);

  const footagePath = overlay.metadata?.footage_path;
  const filename = footagePath ? footagePath.split('/').pop() : null;
  const isDownloading = stockStatus?.status === 'loading';
  const isImage =
    overlay.metadata?.media_type === 'image' ||
    /\.(jpe?g|png|webp|bmp)$/i.test(filename || '');

  return (
    <>
      <div className={styles.stockSearch}>
        <label className={styles.field}>
          Search query
          <input
            type="text"
            value={queryDraft}
            placeholder="e.g. ocean waves"
            onChange={(event) => setQueryDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && queryDraft.trim() && !isDownloading) {
                onRefetchStock(overlay, queryDraft);
              }
            }}
          />
        </label>
        <button
          type="button"
          className={styles.primaryButton}
          disabled={!queryDraft.trim() || isDownloading}
          onClick={() => onRefetchStock(overlay, queryDraft)}
        >
          {isDownloading
            ? 'Downloading…'
            : footagePath
              ? 'Re-search & download'
              : 'Search & download'}
        </button>
      </div>

      {stockStatus?.status === 'error' && (
        <div className={styles.error}>{stockStatus.error}</div>
      )}

      <div className={styles.preview}>
        {filename ? (
          isImage ? (
            <img
              key={filename}
              className={styles.video}
              src={getStockFootageURL(filename)}
              alt={overlay.metadata?.search_query || 'Stock still image'}
            />
          ) : (
            <video
              key={filename}
              className={styles.video}
              src={getStockFootageURL(filename)}
              controls
              preload="metadata"
            />
          )
        ) : (
          <div className={styles.placeholder}>
            No footage downloaded yet — search Pexels above.
          </div>
        )}
      </div>
    </>
  );
}

function DiagramOptions({ overlay, onUpdateOverlay }) {
  const meta = overlay.metadata || {};
  const [titleDraft, setTitleDraft] = useState(meta.title || '');

  useEffect(() => {
    setTitleDraft(overlay.metadata?.title || '');
    // Re-seed the draft only when a different diagram is inspected.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [overlay.id]);

  const commitTitle = () => {
    const next = titleDraft.trim();
    if (next !== (meta.title || '')) {
      onUpdateOverlay(overlay, { metadata: { ...meta, title: next } });
    }
  };

  return (
    <>
      <div className={styles.fields}>
        <label className={styles.field}>
          Diagram type
          <select
            value={meta.diagram_type || 'flowchart'}
            onChange={(event) =>
              onUpdateOverlay(overlay, {
                metadata: { ...meta, diagram_type: event.target.value },
              })
            }
          >
            {DIAGRAM_TYPES.map((type) => (
              <option key={type} value={type}>
                {type}
              </option>
            ))}
          </select>
        </label>
        <label className={styles.field}>
          Title
          <input
            type="text"
            value={titleDraft}
            placeholder="On-screen title"
            onChange={(event) => setTitleDraft(event.target.value)}
            onBlur={commitTitle}
            onKeyDown={(event) => {
              if (event.key === 'Enter') event.currentTarget.blur();
            }}
          />
        </label>
      </div>

      {meta.transcript_excerpt && (
        <p className={styles.excerpt}>“{meta.transcript_excerpt}”</p>
      )}
      {meta.reason && <p className={styles.note}>{meta.reason}</p>}
    </>
  );
}

function OverlayInspector({
  overlay,
  sourceDuration,
  stockStatus,
  onUpdateOverlay,
  onDeleteOverlay,
  onRefetchStock,
}) {
  const duration = overlay.end - overlay.start;

  return (
    <>
      <p className={styles.info}>
        {formatTime(overlay.start)} – {formatTime(overlay.end)} ·{' '}
        {formatTime(duration)} long
        {overlay.enabled === false && ' · disabled'}
      </p>

      <div className={styles.fields}>
        <NumberField
          label="Start (s)"
          value={overlay.start}
          min={0}
          max={overlay.end - MIN_LENGTH}
          onCommit={(start) => onUpdateOverlay(overlay, { start })}
        />
        <NumberField
          label="End (s)"
          value={overlay.end}
          min={overlay.start + MIN_LENGTH}
          max={sourceDuration}
          onCommit={(end) => onUpdateOverlay(overlay, { end })}
        />
        <NumberField
          label="Duration (s)"
          value={duration}
          min={MIN_LENGTH}
          max={sourceDuration - overlay.start}
          onCommit={(value) =>
            onUpdateOverlay(overlay, {
              end: round2(
                clamp(overlay.start + value, overlay.start + MIN_LENGTH, sourceDuration)
              ),
            })
          }
        />
      </div>

      {overlay.type === 'zoom' && (
        <ZoomOptions overlay={overlay} onUpdateOverlay={onUpdateOverlay} />
      )}
      {overlay.type === 'insert_stock_footage' && (
        <StockOptions
          overlay={overlay}
          stockStatus={stockStatus}
          onRefetchStock={onRefetchStock}
        />
      )}
      {overlay.type === 'diagram' && (
        <DiagramOptions overlay={overlay} onUpdateOverlay={onUpdateOverlay} />
      )}

      <div className={styles.actions}>
        <label className={styles.enabledToggle}>
          <input
            type="checkbox"
            checked={overlay.enabled !== false}
            onChange={(event) =>
              onUpdateOverlay(overlay, { enabled: event.target.checked })
            }
          />
          Enabled (applied on render)
        </label>
        <button
          type="button"
          className={styles.dangerButton}
          onClick={() => onDeleteOverlay(overlay)}
        >
          Delete
        </button>
      </div>
    </>
  );
}

/**
 * Detail panel for whatever is selected on the timeline: a base video
 * segment or an overlay clip (zoom / B-roll / diagram), with per-type
 * editable options.
 */
export default function InspectorPanel({
  selection,
  segmentCount,
  sourceDuration,
  stockStatus,
  onClose,
  onSeek,
  onUpdateSegment,
  onDeleteSegment,
  onUpdateOverlay,
  onDeleteOverlay,
  onRefetchStock,
}) {
  if (!selection) return null;

  const isSegment = selection.kind === 'segment';
  const overlay = isSegment ? null : selection.overlay;
  const badgeClass = isSegment
    ? styles.videoBadge
    : styles[OVERLAY_BADGE_CLASSES[overlay.type]];
  const title = isSegment
    ? `Video segment ${selection.index + 1}`
    : OVERLAY_TYPE_LABELS[overlay.type] || overlay.type;
  const seekTarget = isSegment ? selection.segment.start : overlay.start;

  return (
    <section className={styles.inspector} key={isSegment ? selection.segment.id : overlay.id}>
      <div className={styles.header}>
        <span className={`${styles.badge} ${badgeClass || ''}`}>Inspect</span>
        <strong className={styles.title}>{title}</strong>
        <button
          type="button"
          className={styles.jumpButton}
          onClick={() => onSeek(seekTarget)}
        >
          Jump to {formatTime(seekTarget)}
        </button>
        <button
          type="button"
          className={styles.closeButton}
          aria-label="Close inspector"
          onClick={onClose}
        >
          ✕
        </button>
      </div>

      {isSegment ? (
        <SegmentInspector
          segment={selection.segment}
          index={selection.index}
          segmentCount={segmentCount}
          sourceDuration={sourceDuration}
          onUpdateSegment={onUpdateSegment}
          onDeleteSegment={onDeleteSegment}
        />
      ) : (
        <OverlayInspector
          overlay={overlay}
          sourceDuration={sourceDuration}
          stockStatus={stockStatus}
          onUpdateOverlay={onUpdateOverlay}
          onDeleteOverlay={onDeleteOverlay}
          onRefetchStock={onRefetchStock}
        />
      )}
    </section>
  );
}
