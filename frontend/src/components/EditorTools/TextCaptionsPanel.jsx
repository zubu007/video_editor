import { useState } from 'react';
import { formatTime } from '../../utils/timeFormat';
import styles from './TextCaptionsPanel.module.css';

const POSITIONS = [
  { value: 'bottom', label: 'Bottom' },
  { value: 'middle', label: 'Middle' },
  { value: 'top', label: 'Top' },
];

// One saved caption: its text is edited inline (committed on blur) so typing
// doesn't fire a save on every keystroke.
function CaptionRow({ caption, onUpdate, onToggle, onDelete, onSeek }) {
  const metadata = caption.metadata || {};
  const [draft, setDraft] = useState(metadata.text || '');

  const commitText = () => {
    const text = draft.trim();
    if (!text || text === metadata.text) {
      setDraft(metadata.text || '');
      return;
    }
    onUpdate(caption, { metadata: { ...metadata, text } });
  };

  return (
    <li className={`${styles.row} ${caption.enabled === false ? styles.disabled : ''}`}>
      <div className={styles.rowTop}>
        <button
          type="button"
          className={styles.time}
          onClick={() => onSeek(caption.start)}
          title="Jump to this moment"
        >
          {formatTime(caption.start)}
        </button>
        <label className={styles.toggle}>
          <input
            type="checkbox"
            checked={caption.enabled !== false}
            onChange={() => onToggle(caption)}
          />
          <span>On</span>
        </label>
        <select
          className={styles.position}
          value={metadata.position || 'bottom'}
          onChange={(event) =>
            onUpdate(caption, {
              metadata: { ...metadata, position: event.target.value },
            })
          }
        >
          {POSITIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        <button
          type="button"
          className={styles.remove}
          onClick={() => onDelete(caption)}
        >
          Delete
        </button>
      </div>
      <textarea
        className={styles.rowText}
        value={draft}
        rows={2}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={commitText}
      />
    </li>
  );
}

export default function TextCaptionsPanel({
  captions,
  currentTime,
  hasProject,
  saving,
  error,
  onAdd,
  onUpdate,
  onToggle,
  onDelete,
  onSeek,
}) {
  const [text, setText] = useState('');
  const [position, setPosition] = useState('bottom');

  const handleAdd = async () => {
    const trimmed = text.trim();
    if (!trimmed) return;
    await onAdd(trimmed, { position });
    setText('');
  };

  const sorted = [...(captions || [])].sort((a, b) => a.start - b.start);

  return (
    <section className={styles.panel}>
      <div className={styles.header}>
        <h3>Notes</h3>
        <p>
          Pause at the moment you want to annotate, write a note (a thought, an
          item choice…), and it streams onto the video with a typewriter effect.
        </p>
      </div>

      {error && <div className={styles.error}>{error}</div>}

      {!hasProject ? (
        <p className={styles.empty}>Load a video to start adding notes.</p>
      ) : (
        <>
          <div className={styles.composer}>
            <textarea
              className={styles.input}
              placeholder="Type a note to place at the playhead…"
              value={text}
              rows={3}
              onChange={(event) => setText(event.target.value)}
            />
            <div className={styles.composerRow}>
              <select
                className={styles.position}
                value={position}
                onChange={(event) => setPosition(event.target.value)}
              >
                {POSITIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
              <button
                type="button"
                className={styles.primaryButton}
                onClick={handleAdd}
                disabled={saving || !text.trim()}
              >
                {saving ? 'Adding…' : `Add at ${formatTime(currentTime)}`}
              </button>
            </div>
          </div>

          {sorted.length === 0 ? (
            <p className={styles.empty}>No notes yet.</p>
          ) : (
            <ul className={styles.list}>
              {sorted.map((caption) => (
                <CaptionRow
                  key={caption.id}
                  caption={caption}
                  onUpdate={onUpdate}
                  onToggle={onToggle}
                  onDelete={onDelete}
                  onSeek={onSeek}
                />
              ))}
            </ul>
          )}
        </>
      )}
    </section>
  );
}
