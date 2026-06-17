import { formatTime } from '../../utils/timeFormat';
import styles from './EditingPlanPanel.module.css';

// Human-readable labels for each registered editing feature.
const FEATURE_LABELS = {
  zoom: 'Zoom in',
  insert_stock_footage: 'Insert stock footage',
  text_overlay: 'Text overlay',
};

// Editable parameter fields per feature, mirroring the backend feature registry.
const FEATURE_PARAMS = {
  zoom: [{ name: 'zoom_level', label: 'Zoom level', type: 'number', step: 0.1 }],
  insert_stock_footage: [{ name: 'search_query', label: 'Search query', type: 'text' }],
  text_overlay: [{ name: 'text', label: 'Text', type: 'text' }],
};

function PlanItemCard({ item, onUpdate, onUpdateParam, onDelete }) {
  const label = FEATURE_LABELS[item.feature] || item.feature;
  const params = FEATURE_PARAMS[item.feature] || [];

  return (
    <div className={styles.card}>
      <div className={styles.cardHeader}>
        <span className={styles.feature}>{label}</span>
        <button
          type="button"
          className={styles.removeButton}
          aria-label="Remove edit"
          title="Remove edit"
          onClick={() => onDelete(item.id)}
        >
          ×
        </button>
      </div>

      <div className={styles.fields}>
        <label className={styles.field}>
          Start time (s)
          <input
            type="number"
            min="0"
            step="0.1"
            value={item.start}
            onChange={(event) => onUpdate(item.id, { start: event.target.value })}
          />
        </label>
        <label className={styles.field}>
          End time (s)
          <input
            type="number"
            min="0"
            step="0.1"
            value={item.end}
            onChange={(event) => onUpdate(item.id, { end: event.target.value })}
          />
        </label>

        {params.map((param) => (
          <label key={param.name} className={styles.field}>
            {param.label}
            <input
              type={param.type}
              step={param.step}
              value={item.parameters?.[param.name] ?? ''}
              onChange={(event) => onUpdateParam(item.id, param.name, event.target.value)}
            />
          </label>
        ))}
      </div>

      <span className={styles.timecode}>
        {formatTime(Number(item.start) || 0)} – {formatTime(Number(item.end) || 0)}
      </span>
    </div>
  );
}

export default function EditingPlanPanel({
  plan,
  loading,
  error,
  hasVideo,
  onGenerate,
  onUpdateItem,
  onUpdateItemParam,
  onDeleteItem,
  onSaveZoomEdits,
  savedZoomCount = 0,
}) {
  const zoomCount = plan.filter((item) => item.feature === 'zoom').length;

  return (
    <section className={styles.panel}>
      <div className={styles.header}>
        <div>
          <h3>Editing Plan</h3>
          <p>Generate AI editing suggestions, then tweak or remove each one.</p>
        </div>
        <button
          type="button"
          className={styles.primaryButton}
          onClick={onGenerate}
          disabled={loading || !hasVideo}
        >
          {loading ? 'Generating...' : 'Generate Plan'}
        </button>
      </div>

      {error && <div className={styles.error}>{error}</div>}

      {(zoomCount > 0 || savedZoomCount > 0) && (
        <div className={styles.zoomActions}>
          <button
            type="button"
            className={styles.primaryButton}
            onClick={onSaveZoomEdits}
            disabled={zoomCount === 0}
          >
            {zoomCount > 0
              ? `Save ${zoomCount} zoom edit${zoomCount === 1 ? '' : 's'} to project`
              : 'Zoom edits saved'}
          </button>
          {savedZoomCount > 0 && (
            <span className={styles.zoomSavedNote}>
              {savedZoomCount} zoom effect{savedZoomCount === 1 ? '' : 's'} saved · applied on render
            </span>
          )}
        </div>
      )}

      {plan.length === 0 ? (
        <p className={styles.empty}>
          {loading ? 'Analyzing transcript...' : 'No editing plan yet. Generate one to get started.'}
        </p>
      ) : (
        <div className={styles.list}>
          {plan.map((item) => (
            <PlanItemCard
              key={item.id}
              item={item}
              onUpdate={onUpdateItem}
              onUpdateParam={onUpdateItemParam}
              onDelete={onDeleteItem}
            />
          ))}
        </div>
      )}
    </section>
  );
}
