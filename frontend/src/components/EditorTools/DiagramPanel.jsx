import { formatTime } from '../../utils/timeFormat';
import styles from './DiagramPanel.module.css';

const LAYOUT_OPTIONS = [
  { value: 'landscape', label: 'Landscape' },
  { value: 'portrait', label: 'Portrait' },
];

function DiagramCard({
  suggestion,
  isSaving,
  preview,
  onAccept,
  onDismiss,
  onRenderPreview,
  onSetLayout,
  onSeek,
}) {
  const nodeCount = suggestion.graph?.nodes?.length || 0;
  const isRendering = preview?.status === 'rendering';
  const activeLayout = suggestion.layout || 'landscape';

  return (
    <div className={styles.card}>
      <div className={styles.cardHeader}>
        <span className={styles.title}>
          {suggestion.title || suggestion.diagram_type}
        </span>
        <button
          type="button"
          className={styles.jumpButton}
          onClick={() => onSeek(Number(suggestion.start) || 0)}
        >
          Jump to {formatTime(Number(suggestion.start) || 0)}
        </button>
      </div>

      <div className={styles.meta}>
        <span className={styles.typeBadge}>{suggestion.diagram_type}</span>
        <span className={styles.timecode}>
          {formatTime(Number(suggestion.start) || 0)} –{' '}
          {formatTime(Number(suggestion.end) || 0)}
        </span>
        {nodeCount > 0 && (
          <span className={styles.timecode}>
            {nodeCount} node{nodeCount === 1 ? '' : 's'}
          </span>
        )}
        <div
          className={styles.layoutToggle}
          role="group"
          aria-label="Diagram orientation"
        >
          {LAYOUT_OPTIONS.map((option) => (
            <button
              key={option.value}
              type="button"
              className={
                activeLayout === option.value
                  ? styles.layoutButtonActive
                  : styles.layoutButton
              }
              disabled={isRendering || isSaving}
              onClick={() => onSetLayout(suggestion.id, option.value)}
            >
              {option.label}
            </button>
          ))}
        </div>
      </div>

      {suggestion.transcript_excerpt && (
        <p className={styles.excerpt}>“{suggestion.transcript_excerpt}”</p>
      )}
      {suggestion.reason && <p className={styles.reason}>{suggestion.reason}</p>}

      {preview?.status === 'done' && (
        <video
          className={styles.previewPlayer}
          src={preview.url}
          controls
          preload="metadata"
        />
      )}
      {preview?.status === 'error' && (
        <p className={styles.previewError}>{preview.error}</p>
      )}

      <div className={styles.cardActions}>
        <button
          type="button"
          className={styles.secondaryButton}
          disabled={isRendering}
          onClick={() => onRenderPreview(suggestion)}
        >
          {isRendering
            ? 'Rendering…'
            : preview?.status === 'done'
              ? 'Re-render diagram'
              : 'Render diagram'}
        </button>
        <button
          type="button"
          className={styles.primaryButton}
          disabled={isSaving}
          onClick={() => onAccept(suggestion)}
        >
          {isSaving ? 'Adding…' : 'Add to timeline'}
        </button>
        <button
          type="button"
          className={styles.secondaryButton}
          disabled={isSaving}
          onClick={() => onDismiss(suggestion.id)}
        >
          Dismiss
        </button>
      </div>
    </div>
  );
}

export default function DiagramPanel({
  suggestions,
  loading,
  savingId,
  error,
  hasVideo,
  savedCount = 0,
  previews = {},
  onSuggest,
  onAccept,
  onDismiss,
  onRenderPreview,
  onSetLayout,
  onSeek,
}) {
  return (
    <section className={styles.panel}>
      <div className={styles.header}>
        <div>
          <h3>Diagrams</h3>
          <p>
            Find transcript moments that would benefit from an animated diagram,
            then add the ones you like to the timeline.
          </p>
        </div>
        <button
          type="button"
          className={styles.primaryButton}
          onClick={onSuggest}
          disabled={loading || !hasVideo}
        >
          {loading ? 'Analyzing…' : 'Suggest Diagrams'}
        </button>
      </div>

      {error && <div className={styles.error}>{error}</div>}

      {savedCount > 0 && (
        <span className={styles.savedNote}>
          {savedCount} diagram{savedCount === 1 ? '' : 's'} on the timeline
        </span>
      )}

      {suggestions.length === 0 ? (
        <p className={styles.empty}>
          {loading
            ? 'Analyzing transcript for diagram-worthy moments...'
            : 'No suggestions yet. Generate some to get started.'}
        </p>
      ) : (
        <div className={styles.list}>
          {suggestions.map((suggestion) => (
            <DiagramCard
              key={suggestion.id}
              suggestion={suggestion}
              isSaving={savingId === suggestion.id}
              preview={previews[suggestion.id]}
              onAccept={onAccept}
              onDismiss={onDismiss}
              onRenderPreview={onRenderPreview}
              onSetLayout={onSetLayout}
              onSeek={onSeek}
            />
          ))}
        </div>
      )}
    </section>
  );
}
