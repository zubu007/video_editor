/**
 * Format time in seconds to MM:SS or HH:MM:SS format
 * @param {number} seconds - Time in seconds
 * @returns {string} Formatted time string
 */
export function formatTime(seconds) {
  if (isNaN(seconds) || seconds === null || seconds === undefined) {
    return '0:00';
  }

  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const secs = Math.floor(seconds % 60);

  if (hours > 0) {
    return `${hours}:${padZero(minutes)}:${padZero(secs)}`;
  }
  
  return `${minutes}:${padZero(secs)}`;
}

/**
 * Pad number with leading zero if less than 10
 * @param {number} num - Number to pad
 * @returns {string} Padded number
 */
function padZero(num) {
  return num.toString().padStart(2, '0');
}

/**
 * Convert formatted time string to seconds
 * @param {string} timeString - Time string (MM:SS or HH:MM:SS)
 * @returns {number} Time in seconds
 */
export function parseTime(timeString) {
  const parts = timeString.split(':').map(Number);
  
  if (parts.length === 2) {
    // MM:SS
    return parts[0] * 60 + parts[1];
  } else if (parts.length === 3) {
    // HH:MM:SS
    return parts[0] * 3600 + parts[1] * 60 + parts[2];
  }
  
  return 0;
}

/**
 * Calculate percentage of current time relative to duration
 * @param {number} currentTime - Current time in seconds
 * @param {number} duration - Total duration in seconds
 * @returns {number} Percentage (0-100)
 */
export function getProgressPercentage(currentTime, duration) {
  if (!duration || duration === 0) {
    return 0;
  }
  
  return (currentTime / duration) * 100;
}

/**
 * Calculate time from percentage and duration
 * @param {number} percentage - Percentage (0-100)
 * @param {number} duration - Total duration in seconds
 * @returns {number} Time in seconds
 */
export function getTimeFromPercentage(percentage, duration) {
  return (percentage / 100) * duration;
}
