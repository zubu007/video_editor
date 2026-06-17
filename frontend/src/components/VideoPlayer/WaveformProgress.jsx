import React, { useCallback, useRef, useState, useEffect } from 'react';
import { formatTime } from '../../utils/timeFormat';
import styles from './WaveformProgress.module.css';

function WaveformProgress({ currentTime, duration, onSeek, buffering, waveformData, rangeMarkers = [] }) {
  const containerRef = useRef(null);
  const canvasRef = useRef(null);
  const [isDragging, setIsDragging] = useState(false);
  const [hoverTime, setHoverTime] = useState(null);
  const [hoverX, setHoverX] = useState(null);

  // Draw waveform on canvas
  useEffect(() => {
    if (!canvasRef.current || !waveformData || waveformData.length === 0) return;

    const canvas = canvasRef.current;
    const ctx = canvas.getContext('2d');
    const container = containerRef.current;
    
    if (!container) return;

    // Set canvas size to match container
    const rect = container.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    canvas.style.width = `${rect.width}px`;
    canvas.style.height = `${rect.height}px`;
    ctx.scale(dpr, dpr);

    const width = rect.width;
    const height = rect.height;
    const barWidth = width / waveformData.length;
    const centerY = height / 2;
    const maxBarHeight = height * 0.8;

    // Clear canvas
    ctx.clearRect(0, 0, width, height);

    // Draw waveform bars
    waveformData.forEach((amplitude, index) => {
      const x = index * barWidth;
      const barHeight = amplitude * maxBarHeight;
      const progress = currentTime / duration;
      const isPlayed = index / waveformData.length < progress;

      // Color: played portion is red, unplayed is gray
      ctx.fillStyle = isPlayed ? '#e74c3c' : 'rgba(255, 255, 255, 0.3)';
      
      // Draw bar centered vertically
      ctx.fillRect(
        x,
        centerY - barHeight / 2,
        Math.max(barWidth - 1, 1),
        barHeight
      );
    });

    // Draw playhead indicator
    const playheadX = (currentTime / duration) * width;
    ctx.fillStyle = '#e74c3c';
    ctx.fillRect(playheadX - 1, 0, 2, height);

  }, [waveformData, currentTime, duration]);

  // Redraw on window resize
  useEffect(() => {
    const handleResize = () => {
      // Trigger redraw by updating a dummy state or just rely on the main effect
    };
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  const handleMouseDown = (e) => {
    setIsDragging(true);
    handleSeekToPosition(e);
  };

  const handleMouseMove = (e) => {
    const container = containerRef.current;
    if (!container) return;

    const rect = container.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const percentage = Math.max(0, Math.min(1, x / rect.width));
    const time = percentage * duration;

    setHoverX(x);
    setHoverTime(time);

    if (isDragging) {
      handleSeekToPosition(e);
    }
  };

  const handleMouseLeave = () => {
    setHoverTime(null);
    setHoverX(null);
  };

  const handleMouseUp = () => {
    setIsDragging(false);
  };

  const handleSeekToPosition = useCallback((e) => {
    const container = containerRef.current;
    if (!container) return;

    const rect = container.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const percentage = Math.max(0, Math.min(1, x / rect.width));
    const time = percentage * duration;

    onSeek(time);
  }, [duration, onSeek]);

  useEffect(() => {
    if (isDragging) {
      const handleGlobalMouseMove = (e) => {
        handleSeekToPosition(e);
      };

      const handleGlobalMouseUp = () => {
        setIsDragging(false);
      };

      document.addEventListener('mousemove', handleGlobalMouseMove);
      document.addEventListener('mouseup', handleGlobalMouseUp);

      return () => {
        document.removeEventListener('mousemove', handleGlobalMouseMove);
        document.removeEventListener('mouseup', handleGlobalMouseUp);
      };
    }
  }, [handleSeekToPosition, isDragging]);

  // Show loading state if no waveform data
  if (!waveformData || waveformData.length === 0) {
    return (
      <div className={styles.waveformContainer}>
        <div className={styles.loadingState}>
          {buffering ? (
            <div className={styles.bufferingIndicator}>
              <div className={styles.spinner} />
            </div>
          ) : (
            <div className={styles.placeholder}>Loading waveform...</div>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className={styles.waveformContainer}>
      <div
        ref={containerRef}
        className={styles.waveform}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseLeave={handleMouseLeave}
        onMouseUp={handleMouseUp}
      >
        <canvas ref={canvasRef} className={styles.canvas} />

        {duration > 0 && rangeMarkers.map((marker) => {
          const left = Math.max(0, Math.min(100, (marker.start / duration) * 100));
          const right = Math.max(0, Math.min(100, (marker.end / duration) * 100));
          const width = Math.max(0.3, right - left);
          const markerClass = marker.enabled === false
            ? styles.disabledRange
            : marker.kind === 'stored'
              ? styles.storedRange
              : styles.proposedRange;

          return (
            <button
              key={marker.id}
              type="button"
              className={`${styles.rangeMarker} ${markerClass}`}
              style={{ left: `${left}%`, width: `${width}%` }}
              title={marker.label}
              onClick={(event) => {
                event.stopPropagation();
                onSeek(marker.start);
              }}
            />
          );
        })}

        {hoverTime !== null && hoverX !== null && (
          <div
            className={styles.hoverTime}
            style={{ left: `${hoverX}px` }}
          >
            {formatTime(hoverTime)}
          </div>
        )}

        {buffering && (
          <div
            className={styles.bufferingIndicator}
            style={{ left: `${(currentTime / duration) * 100}%` }}
          />
        )}
      </div>
    </div>
  );
}

export default WaveformProgress;
