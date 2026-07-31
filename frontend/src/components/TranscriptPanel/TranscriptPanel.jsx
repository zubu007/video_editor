import { useEffect, useRef } from 'react';
import styles from './TranscriptPanel.module.css';

/**
 * TranscriptPanel component - displays word-level transcript with timestamps
 * @param {Object} props
 * @param {Array} props.words - Array of word objects {start, end, word}
 * @param {number} props.currentTime - Current playback time in seconds
 * @param {Function} props.onSeek - Callback when user clicks on a word to seek
 * @param {boolean} props.loading - Whether a transcription job is running
 * @param {number} props.progress - Transcription progress (0.0-1.0)
 * @param {boolean} props.hasFile - Whether a video is loaded (enables the start button)
 * @param {Function} props.onStartTranscription - Start the transcription job
 */
export default function TranscriptPanel({
  words = [],
  currentTime = 0,
  onSeek,
  loading = false,
  progress = 0,
  hasFile = false,
  onStartTranscription,
}) {
  const activeWordRef = useRef(null);

  // Auto-scroll to active word
  useEffect(() => {
    if (activeWordRef.current) {
      activeWordRef.current.scrollIntoView({
        behavior: 'smooth',
        block: 'center',
      });
    }
  }, [currentTime]);

  // Find the current word based on playback time
  const getCurrentWordIndex = () => {
    return words.findIndex(
      (word) => currentTime >= word.start && currentTime <= word.end
    );
  };

  const currentWordIndex = getCurrentWordIndex();

  const handleWordClick = (word) => {
    if (onSeek) {
      onSeek(word.start);
    }
  };

  if (loading) {
    const percent = Math.round((progress || 0) * 100);
    return (
      <div className={styles.transcriptPanel}>
        <div className={styles.header}>
          <h2>Transcript</h2>
        </div>
        <div className={styles.loadingContainer}>
          <div className={styles.spinner}></div>
          <p>Transcribing… {percent}%</p>
          <div className={styles.progressTrack}>
            <div
              className={styles.progressFill}
              style={{ width: `${percent}%` }}
            />
          </div>
          <p className={styles.hint}>
            Long videos can take several minutes. You can keep editing while this runs.
          </p>
        </div>
      </div>
    );
  }

  if (!words || words.length === 0) {
    return (
      <div className={styles.transcriptPanel}>
        <div className={styles.header}>
          <h2>Transcript</h2>
        </div>
        <div className={styles.emptyState}>
          {hasFile ? (
            <>
              <p>No transcript yet</p>
              <p className={styles.hint}>
                Transcription runs on demand — it can take a while on long videos.
              </p>
              <button
                type="button"
                className={styles.startButton}
                onClick={onStartTranscription}
                disabled={!onStartTranscription}
              >
                Start transcription
              </button>
            </>
          ) : (
            <>
              <p>No transcript available</p>
              <p className={styles.hint}>Upload a video to see the transcript</p>
            </>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className={styles.transcriptPanel}>
      <div className={styles.header}>
        <h2>Transcript</h2>
        <div className={styles.stats}>
          {words.length} words
        </div>
      </div>
      <div className={styles.transcriptContent}>
        {words.map((word, index) => (
          <span
            key={index}
            ref={index === currentWordIndex ? activeWordRef : null}
            className={`${styles.word} ${
              index === currentWordIndex ? styles.active : ''
            }`}
            onClick={() => handleWordClick(word)}
            title={`${word.start.toFixed(2)}s - ${word.end.toFixed(2)}s`}
          >
            {word.word}
          </span>
        ))}
      </div>
    </div>
  );
}
