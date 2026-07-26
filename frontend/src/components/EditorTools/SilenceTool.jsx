import { formatTime } from '../../utils/timeFormat';
import styles from './SilenceTool.module.css';

function SilenceRangeRow({ range, onToggle, onSeek, variant }) {
  return (
    <div className={`${styles.rangeRow} ${range.enabled === false ? styles.disabled : ''}`}>
      <label className={styles.rangeToggle}>
        <input
          type="checkbox"
          checked={range.enabled !== false}
          onChange={() => onToggle(range.id)}
        />
        <span>
          {formatTime(range.start)} - {formatTime(range.end)}
        </span>
      </label>
      <span className={styles.duration}>{range.duration.toFixed(2)}s</span>
      <button type="button" className={styles.linkButton} onClick={() => onSeek(range.start)}>
        Seek
      </button>
      {variant === 'stored' && (
        <span className={styles.savedBadge}>Saved</span>
      )}
    </div>
  );
}

function StoredEditRow({ edit, onToggle, onSeek, onDelete }) {
  const duration = Math.max(0, edit.end - edit.start);

  return (
    <div className={`${styles.rangeRow} ${edit.enabled === false ? styles.disabled : ''}`}>
      <label className={styles.rangeToggle}>
        <input
          type="checkbox"
          checked={edit.enabled !== false}
          onChange={() => onToggle(edit)}
        />
        <span>
          {formatTime(edit.start)} - {formatTime(edit.end)}
        </span>
      </label>
      <span className={styles.duration}>{duration.toFixed(2)}s</span>
      <button type="button" className={styles.linkButton} onClick={() => onSeek(edit.start)}>
        Seek
      </button>
      <button type="button" className={styles.dangerButton} onClick={() => onDelete(edit)}>
        Remove
      </button>
    </div>
  );
}

export default function SilenceTool({
  detectedPauses,
  editOperations,
  loading,
  error,
  onDetect,
  onToggleProposal,
  onConfirm,
  onToggleEdit,
  onDeleteEdit,
  onSeek,
}) {
  const enabledProposalCount = detectedPauses.filter((pause) => pause.enabled !== false).length;
  const enabledEditCount = editOperations.filter((edit) => edit.enabled !== false).length;

  return (
    <section className={styles.panel}>
      <div className={styles.header}>
        <div>
          <h3>Silence Cuts</h3>
        <p>Detect quiet sections, review them, then save them as cut edits.</p>
        </div>
        <button
          type="button"
          className={styles.primaryButton}
          onClick={onDetect}
          disabled={loading.detecting}
        >
          {loading.detecting ? 'Detecting...' : 'Detect Silence'}
        </button>
      </div>

      {error && <div className={styles.error}>{error}</div>}

      {detectedPauses.length > 0 && (
        <div className={styles.section}>
          <div className={styles.sectionHeader}>
            <h4>Detected silence</h4>
            <span>{enabledProposalCount} selected</span>
          </div>
          <div className={styles.rangeList}>
            {detectedPauses.map((pause) => (
              <SilenceRangeRow
                key={pause.id}
                range={pause}
                variant="proposal"
                onToggle={onToggleProposal}
                onSeek={onSeek}
              />
            ))}
          </div>
          <button
            type="button"
            className={styles.secondaryButton}
            onClick={onConfirm}
            disabled={loading.confirming || enabledProposalCount === 0}
          >
            {loading.confirming ? 'Saving cuts...' : 'Confirm Silence Cuts'}
          </button>
        </div>
      )}

      <div className={styles.section}>
        <div className={styles.sectionHeader}>
          <h4>Edit stack</h4>
          <span>{enabledEditCount} active cuts</span>
        </div>
        {editOperations.length === 0 ? (
          <p className={styles.empty}>No saved cut edits yet.</p>
        ) : (
          <div className={styles.rangeList}>
            {editOperations.map((edit) => (
              <StoredEditRow
                key={edit.id}
                edit={edit}
                onToggle={onToggleEdit}
                onSeek={onSeek}
                onDelete={onDeleteEdit}
              />
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
