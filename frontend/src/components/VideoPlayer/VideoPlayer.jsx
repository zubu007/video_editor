import React, { forwardRef, useEffect, useImperativeHandle } from 'react';
import VideoControls from './VideoControls';
import CaptionOverlay from './CaptionOverlay';
import TextCaptionOverlay from './TextCaptionOverlay';
import useKeyboardControls from '../../hooks/useKeyboardControls';
import useVideoPlayer from '../../hooks/useVideoPlayer';
import styles from './VideoPlayer.module.css';

const VideoPlayer = forwardRef(({ src, onTimeUpdate, onEnded, autoPlay = false, waveformData, rangeMarkers = [], pointMarkers = [], onAspectRatioChange, captionPreview = null, textCaptions = [] }, ref) => {
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
    aspectRatio,
    playbackRate,
  } = state;

  useKeyboardControls({
    enabled: Boolean(src),
    currentTime,
    duration,
    volume,
    controls,
  });

  // Let the parent react to the source orientation (e.g. default new diagram
  // overlays to portrait for portrait videos).
  useEffect(() => {
    if (aspectRatio && onAspectRatioChange) {
      onAspectRatioChange(aspectRatio);
    }
  }, [aspectRatio, onAspectRatioChange]);

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
      <div className={styles.placeholderBox}>
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
      <div className={styles.stage}>
        <div
          className={styles.videoPlayerContainer}
          style={aspectRatio ? { '--video-aspect': aspectRatio } : undefined}
          onClick={controls.togglePlay}
        >
          <video
            ref={videoRef}
            className={styles.video}
            src={src}
            autoPlay={autoPlay}
          />

          {captionPreview && (
            <CaptionOverlay
              words={captionPreview.words}
              style={captionPreview.style}
              wordsPerLine={captionPreview.wordsPerLine}
              currentTime={currentTime}
            />
          )}

          {textCaptions.length > 0 && (
            <TextCaptionOverlay
              captions={textCaptions}
              currentTime={currentTime}
            />
          )}

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
          pointMarkers={pointMarkers}
          playbackRate={playbackRate}
          onPlayPause={controls.togglePlay}
          onSeek={controls.seek}
          onSpeedChange={controls.setPlaybackRate}
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
