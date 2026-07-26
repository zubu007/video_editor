import { useCallback, useEffect, useRef, useState } from 'react';
import {
  exitFullscreen,
  isFullscreen as checkFullscreen,
  requestFullscreen,
} from '../utils/videoUtils';

export default function useVideoPlayer({ onTimeUpdate, onEnded } = {}) {
  const videoRef = useRef(null);
  const wrapperRef = useRef(null);

  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [buffering, setBuffering] = useState(false);
  const [volume, setVolume] = useState(1);
  const [isMuted, setIsMuted] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [error, setError] = useState(null);
  // Width / height of the loaded video, so the player chrome can match the
  // source aspect ratio (portrait vs landscape) instead of assuming 16:9.
  const [aspectRatio, setAspectRatio] = useState(null);

  const safelyPlay = useCallback((video) => {
    const playPromise = video.play();
    if (!playPromise?.catch) return;

    playPromise.catch((playError) => {
      if (playError.name === 'AbortError') {
        return;
      }

      setError('Failed to start playback');
      console.error('Video playback failed:', playError);
    });
  }, []);

  const play = useCallback(() => {
    const video = videoRef.current;
    if (!video) return;

    safelyPlay(video);
  }, [safelyPlay]);

  const pause = useCallback(() => {
    videoRef.current?.pause();
  }, []);

  const togglePlay = useCallback(() => {
    const video = videoRef.current;
    if (!video) return;

    if (video.paused) {
      safelyPlay(video);
    } else {
      video.pause();
    }
  }, [safelyPlay]);

  const seek = useCallback((time) => {
    const video = videoRef.current;
    if (!video || !Number.isFinite(time)) return;

    const targetTime = Math.max(0, Math.min(time, video.duration || time));
    video.currentTime = targetTime;
  }, []);

  const setVolumeLevel = useCallback((newVolume) => {
    const video = videoRef.current;
    if (!video) return;

    const targetVolume = Math.max(0, Math.min(1, newVolume));
    video.volume = targetVolume;
    if (targetVolume > 0 && video.muted) {
      video.muted = false;
    }
  }, []);

  const toggleMute = useCallback(() => {
    const video = videoRef.current;
    if (!video) return;

    video.muted = !video.muted;
  }, []);

  const toggleFullscreen = useCallback(() => {
    if (checkFullscreen()) {
      exitFullscreen();
    } else {
      requestFullscreen(wrapperRef.current);
    }
  }, []);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return undefined;

    const handleLoadedMetadata = () => {
      setDuration(video.duration);
      if (video.videoWidth && video.videoHeight) {
        setAspectRatio(video.videoWidth / video.videoHeight);
      }
      setError(null);
    };

    const handleTimeUpdate = () => {
      setCurrentTime(video.currentTime);
      onTimeUpdate?.(video.currentTime);
    };

    const handlePlay = () => setIsPlaying(true);
    const handlePause = () => setIsPlaying(false);
    const handleEnded = () => {
      setIsPlaying(false);
      onEnded?.();
    };
    const handleVolumeChange = () => {
      setVolume(video.volume);
      setIsMuted(video.muted);
    };
    const handleWaiting = () => setBuffering(true);
    const handleCanPlay = () => setBuffering(false);
    const handleSeeking = () => setBuffering(true);
    const handleSeeked = () => setBuffering(false);
    const handleError = () => {
      setError('Failed to load video');
      setBuffering(false);
    };

    video.addEventListener('loadedmetadata', handleLoadedMetadata);
    video.addEventListener('timeupdate', handleTimeUpdate);
    video.addEventListener('play', handlePlay);
    video.addEventListener('pause', handlePause);
    video.addEventListener('ended', handleEnded);
    video.addEventListener('volumechange', handleVolumeChange);
    video.addEventListener('waiting', handleWaiting);
    video.addEventListener('canplay', handleCanPlay);
    video.addEventListener('seeking', handleSeeking);
    video.addEventListener('seeked', handleSeeked);
    video.addEventListener('error', handleError);

    return () => {
      video.removeEventListener('loadedmetadata', handleLoadedMetadata);
      video.removeEventListener('timeupdate', handleTimeUpdate);
      video.removeEventListener('play', handlePlay);
      video.removeEventListener('pause', handlePause);
      video.removeEventListener('ended', handleEnded);
      video.removeEventListener('volumechange', handleVolumeChange);
      video.removeEventListener('waiting', handleWaiting);
      video.removeEventListener('canplay', handleCanPlay);
      video.removeEventListener('seeking', handleSeeking);
      video.removeEventListener('seeked', handleSeeked);
      video.removeEventListener('error', handleError);
    };
  }, [onEnded, onTimeUpdate]);

  useEffect(() => {
    const handleFullscreenChange = () => {
      setIsFullscreen(checkFullscreen());
    };

    document.addEventListener('fullscreenchange', handleFullscreenChange);
    document.addEventListener('webkitfullscreenchange', handleFullscreenChange);
    document.addEventListener('mozfullscreenchange', handleFullscreenChange);
    document.addEventListener('MSFullscreenChange', handleFullscreenChange);

    return () => {
      document.removeEventListener('fullscreenchange', handleFullscreenChange);
      document.removeEventListener('webkitfullscreenchange', handleFullscreenChange);
      document.removeEventListener('mozfullscreenchange', handleFullscreenChange);
      document.removeEventListener('MSFullscreenChange', handleFullscreenChange);
    };
  }, []);

  return {
    videoRef,
    wrapperRef,
    state: {
      isPlaying,
      currentTime,
      duration,
      buffering,
      volume,
      isMuted,
      isFullscreen,
      error,
      aspectRatio,
    },
    controls: {
      play,
      pause,
      togglePlay,
      seek,
      setVolume: setVolumeLevel,
      toggleMute,
      toggleFullscreen,
    },
  };
}
