import { useEffect, useRef } from 'react';
import styles from './TranscriptPanel.module.css';

/**
 * TranscriptPanel component - displays word-level transcript with timestamps
 * @param {Object} props
 * @param {Array} props.words - Array of word objects {start, end, word}
 * @param {number} props.currentTime - Current playback time in seconds
 * @param {Function} props.onSeek - Callback when user clicks on a word to seek
 * @param {boolean} props.loading - Loading state
 */
export default function TranscriptPanel({ words = [], currentTime = 0, onSeek, loading = false }) {
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
    return (
      <div className={styles.transcriptPanel}>
        <div className={styles.header}>
          <h2>Transcript</h2>
        </div>
        <div className={styles.loadingContainer}>
          <div className={styles.spinner}></div>
          <p>Extracting transcript...</p>
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
          <p>No transcript available</p>
          <p className={styles.hint}>Upload a video to see the transcript</p>
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
