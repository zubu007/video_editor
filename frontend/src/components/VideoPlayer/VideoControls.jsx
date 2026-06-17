import React from 'react';
import PlaybackButton from './PlaybackButton';
import WaveformProgress from './WaveformProgress';
import TimeDisplay from './TimeDisplay';
import VolumeControl from './VolumeControl';
import FullscreenButton from './FullscreenButton';
import styles from './VideoControls.module.css';

function VideoControls({
  isPlaying,
  currentTime,
  duration,
  volume,
  isMuted,
  isFullscreen,
  buffering,
  waveformData,
  rangeMarkers,
  onPlayPause,
  onSeek,
  onVolumeChange,
  onMuteToggle,
  onFullscreenToggle,
}) {
  return (
    <div className={styles.videoControls}>
      <PlaybackButton isPlaying={isPlaying} onClick={onPlayPause} />
      <WaveformProgress
        currentTime={currentTime}
        duration={duration}
        onSeek={onSeek}
        buffering={buffering}
        waveformData={waveformData}
        rangeMarkers={rangeMarkers}
      />
      <TimeDisplay currentTime={currentTime} duration={duration} />
      <VolumeControl
        volume={volume}
        isMuted={isMuted}
        onVolumeChange={onVolumeChange}
        onMuteToggle={onMuteToggle}
      />
      <FullscreenButton isFullscreen={isFullscreen} onClick={onFullscreenToggle} />
    </div>
  );
}

export default VideoControls;
