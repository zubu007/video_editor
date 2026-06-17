import React, { forwardRef, useImperativeHandle } from 'react';
import VideoControls from './VideoControls';
import useKeyboardControls from '../../hooks/useKeyboardControls';
import useVideoPlayer from '../../hooks/useVideoPlayer';
import styles from './VideoPlayer.module.css';

const VideoPlayer = forwardRef(({ src, onTimeUpdate, onEnded, autoPlay = false, waveformData, rangeMarkers = [] }, ref) => {
  const {
    videoRef,
    wrapperRef,
    state,
    controls,
  } = useVideoPlayer({ onTimeUpdate, onEnded });

  const {
    isPlaying,
    currentTime,
    duration,
    buffering,
    volume,
    isMuted,
    isFullscreen,
    error,
  } = state;

  useKeyboardControls({
    enabled: Boolean(src),
    currentTime,
    duration,
    volume,
    controls,
  });

  // Expose seek method to parent component via ref
  useImperativeHandle(ref, () => ({
    seek: (time) => {
      controls.seek(time);
    },
    play: controls.play,
    pause: controls.pause,
    togglePlay: controls.togglePlay,
  }), [controls]);

  if (!src) {
    return (
      <div className={styles.videoPlayerContainer}>
        <div className={styles.placeholder}>
          <svg width="64" height="64" viewBox="0 0 24 24" fill="currentColor">
            <path d="M17 10.5V7c0-.55-.45-1-1-1H4c-.55 0-1 .45-1 1v10c0 .55.45 1 1 1h12c.55 0 1-.45 1-1v-3.5l4 4v-11l-4 4z"/>
          </svg>
          <p>No video selected</p>
        </div>
      </div>
    );
  }

  return (
    <div ref={wrapperRef} className={styles.playerWrapper}>
      <div
        className={styles.videoPlayerContainer}
        onClick={controls.togglePlay}
      >
        <video
          ref={videoRef}
          className={styles.video}
          src={src}
          autoPlay={autoPlay}
        />

        {buffering && (
          <div className={styles.bufferingSpinner}>
            <div className={styles.spinner} />
          </div>
        )}

        {error && (
          <div className={styles.error}>
            <p>{error}</p>
          </div>
        )}
      </div>

      <div className={styles.controlsSection}>
        <VideoControls
          isPlaying={isPlaying}
          currentTime={currentTime}
          duration={duration}
          volume={volume}
          isMuted={isMuted}
          isFullscreen={isFullscreen}
          buffering={buffering}
          waveformData={waveformData}
          rangeMarkers={rangeMarkers}
          onPlayPause={controls.togglePlay}
          onSeek={controls.seek}
          onVolumeChange={controls.setVolume}
          onMuteToggle={controls.toggleMute}
          onFullscreenToggle={controls.toggleFullscreen}
        />
      </div>
    </div>
  );
});

VideoPlayer.displayName = 'VideoPlayer';

export default VideoPlayer;
