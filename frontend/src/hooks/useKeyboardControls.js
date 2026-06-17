import { useEffect } from 'react';

function isEditableTarget(target) {
  if (!target) return false;

  const tagName = target.tagName?.toLowerCase();
  return (
    tagName === 'input' ||
    tagName === 'textarea' ||
    tagName === 'select' ||
    target.isContentEditable
  );
}

export default function useKeyboardControls({
  enabled,
  currentTime,
  duration,
  volume,
  controls,
}) {
  useEffect(() => {
    if (!enabled) return undefined;

    const handleKeyDown = (event) => {
      if (isEditableTarget(event.target)) return;

      const seekBy = (delta) => {
        controls.seek(currentTime + delta);
      };

      switch (event.key) {
        case ' ':
          event.preventDefault();
          controls.togglePlay();
          break;
        case 'ArrowLeft':
          event.preventDefault();
          seekBy(-5);
          break;
        case 'ArrowRight':
          event.preventDefault();
          seekBy(5);
          break;
        case 'ArrowUp':
          event.preventDefault();
          controls.setVolume(volume + 0.1);
          break;
        case 'ArrowDown':
          event.preventDefault();
          controls.setVolume(volume - 0.1);
          break;
        case 'f':
        case 'F':
          event.preventDefault();
          controls.toggleFullscreen();
          break;
        case 'm':
        case 'M':
          event.preventDefault();
          controls.toggleMute();
          break;
        default:
          if (/^[0-9]$/.test(event.key) && duration > 0) {
            event.preventDefault();
            controls.seek((Number(event.key) / 10) * duration);
          }
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [controls, currentTime, duration, enabled, volume]);
}
