import React from 'react';
import { formatTime } from '../../utils/timeFormat';
import styles from './TimeDisplay.module.css';

function TimeDisplay({ currentTime, duration }) {
  return (
    <div className={styles.timeDisplay}>
      <span className={styles.currentTime}>{formatTime(currentTime)}</span>
      <span className={styles.separator}> / </span>
      <span className={styles.duration}>{formatTime(duration)}</span>
    </div>
  );
}

export default TimeDisplay;
