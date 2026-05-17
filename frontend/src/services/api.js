import axios from 'axios';

// Base URL for the API - can be overridden with environment variable
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

// Create axios instance with default config
const apiClient = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

/**
 * Upload video file to backend
 * @param {File} file - Video file to upload
 * @param {Function} onProgress - Progress callback (percentage)
 * @returns {Promise<{file_id: string, file_url: string, duration: number, size: number, filename: string}>}
 */
export async function uploadVideo(file, onProgress) {
  const formData = new FormData();
  formData.append('video', file);

  const response = await apiClient.post('/api/video/upload', formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
    onUploadProgress: (progressEvent) => {
      if (onProgress && progressEvent.total) {
        const percentCompleted = Math.round(
          (progressEvent.loaded * 100) / progressEvent.total
        );
        onProgress(percentCompleted);
      }
    },
  });

  return response.data;
}

/**
 * Get video file URL
 * @param {string} fileId - File ID
 * @returns {string} Video URL
 */
export function getVideoURL(fileId) {
  return `${API_BASE_URL}/api/video/${fileId}`;
}

/**
 * Extract transcript from video
 * @param {string} fileId - File ID
 * @param {string} modelSize - Whisper model size (tiny, base, small, medium, large)
 * @returns {Promise<{language: string, segments: Array}>}
 */
export async function extractTranscript(fileId, modelSize = 'base') {
  const response = await apiClient.post('/api/transcript/segments', {
    file_id: fileId,
    model_size: modelSize,
  });

  return response.data;
}

/**
 * Extract word-level transcript from video
 * @param {string} fileId - File ID
 * @param {string} modelSize - Whisper model size
 * @returns {Promise<{language: string, words: Array}>}
 */
export async function extractWords(fileId, modelSize = 'base') {
  const response = await apiClient.get(`/api/transcript/words/${fileId}`, {
    params: { model_size: modelSize },
  });

  return response.data;
}

/**
 * Detect filler words in video
 * @param {string} fileId - File ID
 * @param {string} modelSize - Whisper model size
 * @returns {Promise<{filler_word_ranges: Array, count: number}>}
 */
export async function detectFillerWords(fileId, modelSize = 'base') {
  const response = await apiClient.post('/api/filler-words/detect', {
    file_id: fileId,
    model_size: modelSize,
  });

  return response.data;
}

/**
 * Generate editing plan for video
 * @param {string} fileId - File ID
 * @param {string} modelSize - Whisper model size
 * @param {string} additionalContext - Additional context for AI
 * @returns {Promise<{editing_plan: Array}>}
 */
export async function generateEditingPlan(fileId, modelSize = 'base', additionalContext = '') {
  const response = await apiClient.post('/api/editing-plan/generate', {
    file_id: fileId,
    model_size: modelSize,
    additional_context: additionalContext,
  });

  return response.data;
}

/**
 * Health check
 * @returns {Promise<{status: string}>}
 */
export async function healthCheck() {
  const response = await apiClient.get('/health');
  return response.data;
}

/**
 * Get waveform data for video
 * @param {string} fileId - File ID
 * @param {number} numSamples - Number of waveform samples (default: 2000)
 * @returns {Promise<{waveform: number[], duration: number, sample_rate: number, num_samples: number}>}
 */
export async function getWaveformData(fileId, numSamples = 2000) {
  const response = await apiClient.get(`/api/audio/waveform/${fileId}`, {
    params: { num_samples: numSamples },
  });

  return response.data;
}

export default apiClient;
