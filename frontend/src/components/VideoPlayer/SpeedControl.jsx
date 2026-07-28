import React from 'react';
import styles from './SpeedControl.module.css';

const SPEEDS = [
  { rate: 1, label: '1×', title: 'Normal speed' },
  { rate: 2, label: '2×', title: 'Play at 2× speed' },
  { rate: 4, label: '4×', title: 'Play at 4× speed' },
];

function SpeedControl({ playbackRate, onSpeedChange }) {
  return (
    <div className={styles.speedControl} role="group" aria-label="Playback speed">
      {SPEEDS.map(({ rate, label, title }) => (
        <button
          key={rate}
          type="button"
          className={`${styles.speedButton} ${playbackRate === rate ? styles.active : ''}`}
          onClick={() => onSpeedChange(rate)}
          title={title}
          aria-pressed={playbackRate === rate}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

export default SpeedControl;
