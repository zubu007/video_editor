import React, { useRef, useState } from 'react';
import { formatTime, getProgressPercentage, getTimeFromPercentage } from '../../utils/timeFormat';
import styles from './ProgressBar.module.css';

function ProgressBar({ currentTime, duration, onSeek, buffering }) {
  const progressBarRef = useRef(null);
  const [isDragging, setIsDragging] = useState(false);
  const [hoverTime, setHoverTime] = useState(null);
  const [hoverPosition, setHoverPosition] = useState(0);

  const progress = getProgressPercentage(currentTime, duration);

  const handleSeek = (clientX) => {
    if (!progressBarRef.current || !duration) return;

    const rect = progressBarRef.current.getBoundingClientRect();
    const percentage = Math.max(0, Math.min(100, ((clientX - rect.left) / rect.width) * 100));
    const time = getTimeFromPercentage(percentage, duration);
    
    onSeek(time);
  };

  const handleMouseDown = (e) => {
    setIsDragging(true);
    handleSeek(e.clientX);
  };

  const handleMouseMove = (e) => {
    if (!progressBarRef.current || !duration) return;

    const rect = progressBarRef.current.getBoundingClientRect();
    const percentage = Math.max(0, Math.min(100, ((e.clientX - rect.left) / rect.width) * 100));
    const time = getTimeFromPercentage(percentage, duration);
    
    setHoverTime(time);
    setHoverPosition(e.clientX - rect.left);

    if (isDragging) {
      handleSeek(e.clientX);
    }
  };

  const handleMouseUp = () => {
    setIsDragging(false);
  };

  const handleMouseLeave = () => {
    setHoverTime(null);
    setIsDragging(false);
  };

  React.useEffect(() => {
    if (isDragging) {
      const handleGlobalMouseMove = (e) => handleSeek(e.clientX);
      const handleGlobalMouseUp = () => setIsDragging(false);

      document.addEventListener('mousemove', handleGlobalMouseMove);
      document.addEventListener('mouseup', handleGlobalMouseUp);

      return () => {
        document.removeEventListener('mousemove', handleGlobalMouseMove);
        document.removeEventListener('mouseup', handleGlobalMouseUp);
      };
    }
  }, [isDragging]);

  return (
    <div className={styles.progressBarContainer}>
      <div
        ref={progressBarRef}
        className={styles.progressBar}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseLeave}
        role="slider"
        aria-label="Video progress"
        aria-valuemin="0"
        aria-valuemax={duration}
        aria-valuenow={currentTime}
      >
        <div className={styles.progressTrack}>
          <div
            className={styles.progressFill}
            style={{ width: `${progress}%` }}
          />
          {buffering && (
            <div className={styles.bufferingIndicator} style={{ left: `${progress}%` }} />
          )}
        </div>
        
        {hoverTime !== null && (
          <div
            className={styles.hoverTime}
            style={{ left: `${hoverPosition}px` }}
          >
            {formatTime(hoverTime)}
          </div>
        )}
      </div>
    </div>
  );
}

export default ProgressBar;
