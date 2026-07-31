import { formatTime } from '../../utils/timeFormat';
import { getAbsoluteAPIURL } from '../../services/api';
import styles from './HighlightsPanel.module.css';

const TEAMS = [
  { value: 'radiant', label: 'Radiant' },
  { value: 'dire', label: 'Dire' },
];

// Gaming-mode "Highlights" tab: detect K/D/A markers (with its own team/slot
// control), then type (or grab from the playhead) a start and end time and trim
// a quick standalone clip between them for download/preview.
export default function HighlightsPanel({
  hasVideo,
  currentTime,
  start,
  end,
  square, // reframe the clip to a square reel
  status, // 'idle' | 'creating' | 'done' | 'error'
  error,
  result, // { filename, output_url, duration } once created
  markerStatus, // 'idle' | 'detecting' | 'done' | 'error'
  markerError,
  markerCount,
  team,
  slots, // array of thumbnail data URLs (empty until loaded)
  selectedSlot, // user's manual override, or null
  playerSlot, // auto-identified slot, or null
  confidence,
  slotsLoading,
  slotError,
  onChangeTeam,
  onLoadSlots,
  onSelectSlot,
  onDetectMarkers,
  onChangeStart,
  onChangeEnd,
  onChangeSquare,
  onSetToPlayhead,
  onCreate,
}) {
  const creating = status === 'creating';
  const detectingMarkers = markerStatus === 'detecting';
  const activeSlot = selectedSlot ?? playerSlot;
  const startNum = parseFloat(start);
  const endNum = parseFloat(end);
  const validRange =
    !Number.isNaN(startNum) && !Number.isNaN(endNum) && endNum > startNum;
  const clipUrl = result ? getAbsoluteAPIURL(result.output_url) : null;

  return (
    <section className={styles.panel}>
      <div className={styles.header}>
        <h3>Highlights</h3>
        <p>
          Cut a quick clip between two timestamps. Use “Set to playhead” to grab
          the current time from the player.
        </p>
      </div>

      {!hasVideo && <p className={styles.empty}>Upload a video first.</p>}

      <div className={styles.markers}>
        <div className={styles.teamRow}>
          <span>Your team</span>
          <div className={styles.segmented}>
            {TEAMS.map((t) => (
              <button
                key={t.value}
                type="button"
                className={team === t.value ? styles.segOn : ''}
                onClick={() => onChangeTeam(t.value)}
                disabled={!hasVideo || detectingMarkers || slotsLoading}
              >
                {t.label}
              </button>
            ))}
          </div>
        </div>

        {/* Manual slot selector — the backup when the auto match is wrong. */}
        <div className={styles.slotHead}>
          <strong>Your hero</strong>
          {playerSlot != null && (
            <span className={styles.detected}>
              auto: slot {playerSlot + 1}
              {confidence != null && ` (${Math.round(confidence * 100)}%)`}
            </span>
          )}
        </div>
        {slots.length === 0 ? (
          <button
            type="button"
            className={styles.textButton}
            onClick={onLoadSlots}
            disabled={!hasVideo || slotsLoading}
          >
            {slotsLoading ? 'Loading portraits…' : 'Wrong hero? Pick it manually'}
          </button>
        ) : (
          <>
            <p className={styles.hint}>
              Click your hero if the highlighted one is wrong.
            </p>
            <div className={styles.slotGrid}>
              {slots.map((thumb, index) => (
                <button
                  key={index}
                  type="button"
                  className={`${styles.slotCard} ${
                    index === activeSlot ? styles.slotActive : ''
                  }`}
                  onClick={() => onSelectSlot(index)}
                  title={`Slot ${index + 1}`}
                >
                  <img src={thumb} alt={`Slot ${index + 1}`} />
                  <span>{index + 1}</span>
                </button>
              ))}
            </div>
          </>
        )}
        {slotError && <div className={styles.error}>{slotError}</div>}

        <button
          type="button"
          className={styles.primaryButton}
          disabled={!hasVideo || detectingMarkers || slotsLoading}
          onClick={onDetectMarkers}
        >
          {detectingMarkers
            ? 'Detecting…'
            : selectedSlot != null
              ? `Detect K/D/A markers (slot ${selectedSlot + 1})`
              : 'Detect K/D/A markers'}
        </button>
        <p className={styles.hint}>
          Scans the HUD for kills, deaths and assists and drops markers on the
          play bar. The OCR pass takes a minute or two.
        </p>
        <div className={styles.legend}>
          <span className={styles.legendK}>K kill</span>
          <span className={styles.legendD}>D death</span>
          <span className={styles.legendA}>A assist</span>
        </div>
        {markerStatus === 'done' && (
          <p className={styles.hint}>Placed {markerCount} markers on the play bar.</p>
        )}
        {markerError && <div className={styles.error}>{markerError}</div>}
      </div>

      <div className={styles.fields}>
        <div className={styles.field}>
          <label htmlFor="highlight-start">Start (s)</label>
          <input
            id="highlight-start"
            type="number"
            min="0"
            step="0.1"
            value={start}
            placeholder="0.0"
            disabled={!hasVideo || creating}
            onChange={(event) => onChangeStart(event.target.value)}
          />
          <button
            type="button"
            className={styles.playheadButton}
            disabled={!hasVideo || creating}
            onClick={() => onSetToPlayhead('start')}
          >
            ⤓ Set to playhead ({formatTime(currentTime)})
          </button>
        </div>

        <div className={styles.field}>
          <label htmlFor="highlight-end">End (s)</label>
          <input
            id="highlight-end"
            type="number"
            min="0"
            step="0.1"
            value={end}
            placeholder="0.0"
            disabled={!hasVideo || creating}
            onChange={(event) => onChangeEnd(event.target.value)}
          />
          <button
            type="button"
            className={styles.playheadButton}
            disabled={!hasVideo || creating}
            onClick={() => onSetToPlayhead('end')}
          >
            ⤓ Set to playhead ({formatTime(currentTime)})
          </button>
        </div>
      </div>

      {validRange && (
        <p className={styles.hint}>
          Clip length: {formatTime(endNum - startNum)}
        </p>
      )}

      <label className={styles.toggle}>
        <input
          type="checkbox"
          checked={square}
          disabled={!hasVideo || creating}
          onChange={(event) => onChangeSquare(event.target.checked)}
        />
        <span>
          <strong>Crop to square for reels</strong>
          Trims equally from both sides, then puts the minimap back in the
          bottom-left corner and K/D&#47;A below the hero bar.
        </span>
      </label>
      {square && (
        <p className={styles.hint}>
          Needs a landscape recording with the standard Dota HUD.
        </p>
      )}

      <button
        type="button"
        className={styles.primaryButton}
        disabled={!hasVideo || !validRange || creating}
        onClick={onCreate}
      >
        {creating ? 'Creating…' : 'Create highlight'}
      </button>

      {error && <div className={styles.error}>{error}</div>}

      {result && clipUrl && (
        <div className={styles.result}>
          <div className={styles.resultHead}>
            <span>Clip ready · {result.duration.toFixed(1)}s</span>
          </div>
          <video className={styles.preview} src={clipUrl} controls preload="metadata" />
          <a className={styles.download} href={clipUrl} download={result.filename}>
            Download clip
          </a>
        </div>
      )}
    </section>
  );
}
