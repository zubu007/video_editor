import { formatTime } from '../../utils/timeFormat';
import styles from './DeathCutsPanel.module.css';

const TEAMS = [
  { value: 'radiant', label: 'Radiant' },
  { value: 'dire', label: 'Dire' },
];

// Panel for the Dota 2 gaming mode: detect death time from the HUD and add the
// dead stretches as cuts. Includes a manual slot selector as a backup for when
// the colour-match picks the wrong hero.
export default function DeathCutsPanel({
  hasProject,
  team,
  onChangeTeam,
  status, // 'idle' | 'loading-slots' | 'detecting' | 'done' | 'error'
  error,
  intervals,
  playerSlot,
  confidence,
  slots, // array of thumbnail data URLs (empty until loaded)
  selectedSlot, // user's manual override, or null
  onLoadSlots,
  onSelectSlot,
  onDetect,
  onSeek,
  onAddCuts,
  savedCount,
}) {
  const detecting = status === 'detecting';
  const loadingSlots = status === 'loading-slots';
  const activeSlot = selectedSlot ?? playerSlot;
  const totalDead = intervals.reduce((sum, iv) => sum + iv.duration, 0);

  return (
    <section className={styles.panel}>
      <div className={styles.header}>
        <h3>Death cuts</h3>
        <p>
          Scan the Dota 2 HUD for your deaths and cut out the time spent dead.
          Reads the respawn box under your top-bar portrait — no game files
          needed.
        </p>
      </div>

      {error && <div className={styles.error}>{error}</div>}

      {!hasProject ? (
        <p className={styles.empty}>Load a gaming video to detect deaths.</p>
      ) : (
        <>
          <div className={styles.controls}>
            <div className={styles.teamRow}>
              <span>Your team</span>
              <div className={styles.segmented}>
                {TEAMS.map((t) => (
                  <button
                    key={t.value}
                    type="button"
                    className={team === t.value ? styles.segOn : ''}
                    onClick={() => onChangeTeam(t.value)}
                    disabled={detecting || loadingSlots}
                  >
                    {t.label}
                  </button>
                ))}
              </div>
            </div>

            <button
              type="button"
              className={styles.primaryButton}
              onClick={onDetect}
              disabled={detecting || loadingSlots}
            >
              {detecting
                ? 'Scanning the match…'
                : selectedSlot != null
                  ? `Detect deaths (slot ${selectedSlot + 1})`
                  : 'Detect deaths'}
            </button>
            <p className={styles.hint}>Takes a minute or two for a full match.</p>
          </div>

          {/* Manual slot selector — the backup when the auto match is wrong. */}
          <div className={styles.slotSection}>
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
                disabled={loadingSlots}
              >
                {loadingSlots ? 'Loading portraits…' : 'Wrong hero? Pick it manually'}
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
          </div>

          {status === 'done' && (
            <div className={styles.results}>
              {intervals.length === 0 ? (
                <p className={styles.empty}>
                  No deaths detected. If that looks wrong, pick your hero above and
                  detect again.
                </p>
              ) : (
                <>
                  <div className={styles.resultsHead}>
                    <strong>
                      {intervals.length} death{intervals.length > 1 ? 's' : ''}
                    </strong>
                    <span>{formatTime(totalDead)} dead</span>
                  </div>
                  <ul className={styles.list}>
                    {intervals.map((iv, index) => (
                      <li key={index} className={styles.row}>
                        <button
                          type="button"
                          className={styles.time}
                          onClick={() => onSeek(iv.start)}
                        >
                          {formatTime(iv.start)} → {formatTime(iv.end)}
                        </button>
                        <span className={styles.dur}>{Math.round(iv.duration)}s</span>
                      </li>
                    ))}
                  </ul>
                  <button
                    type="button"
                    className={styles.primaryButton}
                    onClick={onAddCuts}
                  >
                    Add {intervals.length} cut{intervals.length > 1 ? 's' : ''} to
                    project
                  </button>
                </>
              )}
            </div>
          )}

          {savedCount > 0 && (
            <p className={styles.saved}>{savedCount} death cuts saved to the project.</p>
          )}
        </>
      )}
    </section>
  );
}
