import styles from './CaptionsPanel.module.css';

const SAMPLE_WORDS = ['This', 'is', 'great'];

// A miniature rendering of a preset, using the same colour/highlight rules as
// the live overlay (second word shown as the "active" one).
function StyleCard({ style, selected, onSelect }) {
  const wordColour = (index) => {
    if (index === 1 && style.highlight_colour) return style.highlight_colour;
    if (style.word_colours.length > 0) {
      return style.word_colours[index % style.word_colours.length];
    }
    return style.text_colour;
  };

  return (
    <button
      type="button"
      className={`${styles.styleCard} ${selected ? styles.selected : ''}`}
      onClick={() => onSelect(style.name)}
    >
      <span
        className={styles.sample}
        style={{
          fontFamily: `'${style.font_family}', 'Arial Black', Impact, sans-serif`,
          textTransform: style.uppercase ? 'uppercase' : 'none',
        }}
      >
        {SAMPLE_WORDS.map((word, index) => (
          <span
            key={word}
            className={styles.sampleWord}
            style={{
              color: wordColour(index),
              transform:
                index === 1 && style.pop_scale
                  ? `scale(${style.pop_scale / 100})`
                  : undefined,
            }}
          >
            {word}
          </span>
        ))}
      </span>
      <span className={styles.styleName}>{style.name.replace('-', ' ')}</span>
    </button>
  );
}

export default function CaptionsPanel({
  captionStyles,
  selectedStyle,
  wordsPerLine,
  savedCaptions,
  hasWords,
  saving,
  error,
  onSelectStyle,
  onChangeWordsPerLine,
  onSave,
  onToggle,
  onDelete,
}) {
  const saved = savedCaptions[0] || null;
  const savedStyleName = saved?.metadata?.style;
  const isDirty =
    !saved ||
    savedStyleName !== selectedStyle ||
    (saved.metadata?.max_words_per_line ?? null) !== (wordsPerLine ?? null);

  return (
    <section className={styles.panel}>
      <div className={styles.header}>
        <div>
          <h3>Captions</h3>
          <p>
            Burn animated word-by-word captions into the render. Pick a style to
            preview it live on the player.
          </p>
        </div>
      </div>

      {error && <div className={styles.error}>{error}</div>}

      {!hasWords && (
        <p className={styles.empty}>
          Captions need the word transcript — load a video first.
        </p>
      )}

      <div className={styles.styleGrid}>
        {captionStyles.map((style) => (
          <StyleCard
            key={style.name}
            style={style}
            selected={style.name === selectedStyle}
            onSelect={onSelectStyle}
          />
        ))}
      </div>

      <label className={styles.wordsPerLine}>
        Words on screen
        <select
          value={wordsPerLine ?? ''}
          onChange={(event) =>
            onChangeWordsPerLine(
              event.target.value === '' ? null : Number(event.target.value)
            )
          }
        >
          <option value="">Style default</option>
          {[1, 2, 3, 4, 5].map((count) => (
            <option key={count} value={count}>
              {count}
            </option>
          ))}
        </select>
      </label>

      <button
        type="button"
        className={styles.primaryButton}
        onClick={onSave}
        disabled={saving || !hasWords || !selectedStyle || !isDirty}
      >
        {saving
          ? 'Saving...'
          : saved
            ? 'Update captions'
            : 'Add captions to render'}
      </button>

      {saved && (
        <div className={styles.savedRow}>
          <label className={styles.savedToggle}>
            <input
              type="checkbox"
              checked={saved.enabled !== false}
              onChange={() => onToggle(saved)}
            />
            <span>
              <strong>{savedStyleName || 'default'}</strong> captions saved
              {saved.enabled === false ? ' (disabled)' : ''}
            </span>
          </label>
          <button
            type="button"
            className={styles.dangerButton}
            onClick={() => onDelete(saved)}
          >
            Remove
          </button>
        </div>
      )}
    </section>
  );
}
