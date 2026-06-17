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
 * @returns {Promise<{file_id: string, file_url: string, duration: number, size: number, filename: string, project_id: string, media_asset_id: string}>}
 */
export async function uploadVideo(file, onProgress, projectId = null) {
  const formData = new FormData();
  formData.append('video', file);
  if (projectId) {
    formData.append('project_id', projectId);
  }

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
 * Convert API-relative URLs to absolute URLs
 * @param {string} url - API-relative or absolute URL
 * @returns {string} Absolute URL
 */
export function getAbsoluteAPIURL(url) {
  if (!url) return '';
  if (url.startsWith('http')) return url;
  return `${API_BASE_URL}${url}`;
}

/**
 * Extract transcript from video
 * @param {string} fileId - File ID
 * @param {string} modelSize - Whisper model size (tiny, base, small, medium, large)
 * @returns {Promise<{language: string, segments: Array}>}
 */
export async function extractTranscript(fileId, modelSize = 'base') {
  const response = await apiClient.get(`/api/transcript/segments/${fileId}`, {
    params: { model_size: modelSize },
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
  const response = await apiClient.get(`/api/filler-words/detect/${fileId}`, {
    params: { model_size: modelSize },
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
  const response = await apiClient.post(`/api/editing-plan/generate/${fileId}`, {
    model_size: modelSize,
    additional_context: additionalContext,
  });

  return response.data;
}

/**
 * Remove detected filler words from an uploaded video
 * @param {string} fileId - File ID
 * @param {string} modelSize - Whisper model size
 * @returns {Promise<Blob>} Edited video blob
 */
export async function cutFillerWords(fileId, modelSize = 'base') {
  const response = await apiClient.post(
    `/api/video/cut-filler-words/${fileId}`,
    null,
    {
      params: { model_size: modelSize },
      responseType: 'blob',
    }
  );

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

/**
 * Detect silence ranges in uploaded video audio
 * @param {string} fileId - File ID
 * @param {Object} settings - Detection settings
 * @returns {Promise<{pauses: Array, count: number, total_silence_duration: number, settings: Object}>}
 */
export async function detectAudioPauses(fileId, settings = {}) {
  const response = await apiClient.get(`/api/audio/pauses/${fileId}`, {
    params: {
      min_silence_duration: settings.minSilenceDuration ?? 1.0,
      silence_threshold: settings.silenceThreshold ?? -40,
      seek_step: settings.seekStep ?? 10,
      merge_gap: settings.mergeGap ?? 0.5,
    },
  });

  return response.data;
}

/**
 * Fetch persisted edit operations for a project
 * @param {string} projectId - Project ID
 * @returns {Promise<{edits: Array}>}
 */
export async function getProjectEdits(projectId) {
  const response = await apiClient.get(`/api/projects/${projectId}/edits`);
  return response.data;
}

/**
 * Persist multiple edit operations for a project
 * @param {string} projectId - Project ID
 * @param {Array} edits - Edit operations
 * @returns {Promise<{edits: Array}>}
 */
export async function createProjectEdits(projectId, edits) {
  const response = await apiClient.post(`/api/projects/${projectId}/edits/bulk`, {
    edits,
  });
  return response.data;
}

/**
 * Update one persisted edit operation
 * @param {string} projectId - Project ID
 * @param {string} editId - Edit ID
 * @param {Object} changes - Edit changes
 * @returns {Promise<Object>}
 */
export async function updateProjectEdit(projectId, editId, changes) {
  const response = await apiClient.patch(
    `/api/projects/${projectId}/edits/${editId}`,
    changes
  );
  return response.data;
}

/**
 * Delete one persisted edit operation
 * @param {string} projectId - Project ID
 * @param {string} editId - Edit ID
 * @returns {Promise<{status: string}>}
 */
export async function deleteProjectEdit(projectId, editId) {
  const response = await apiClient.delete(`/api/projects/${projectId}/edits/${editId}`);
  return response.data;
}

/**
 * Download stock footage (B-roll) from Pexels for a search query.
 * @param {string} searchTerm - Search query (e.g. 'ocean waves')
 * @param {string} quality - Video quality (hd, sd, original)
 * @returns {Promise<{file_path: string, search_term: string}>}
 */
export async function downloadStockFootage(searchTerm, quality = 'hd') {
  const formData = new FormData();
  formData.append('search_term', searchTerm);
  formData.append('quality', quality);
  const response = await apiClient.post('/api/stock-footage/download', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return response.data;
}

/**
 * Build a playable URL for a previously downloaded stock footage file.
 * @param {string} filename - Basename of the downloaded clip
 * @returns {string} Absolute URL the <video> element can stream from
 */
export function getStockFootageURL(filename) {
  return `${API_BASE_URL}/api/stock-footage/download/${encodeURIComponent(filename)}`;
}

/**
 * Render a project with enabled edits
 * @param {string} projectId - Project ID
 * @returns {Promise<{output_url: string, filename: string, applied_edits: number}>}
 */
export async function renderProject(projectId) {
  const response = await apiClient.post(`/api/projects/${projectId}/render`);
  return response.data;
}

/**
 * Start a background job that removes burned-in captions from a video.
 * @param {string} fileId - Uploaded file ID
 * @param {{ mode?: string, useGpu?: boolean }} [options] - Inpainting mode and GPU toggle.
 *   When useGpu is undefined the backend falls back to its SUBTITLE_REMOVER_USE_GPU env var.
 * @returns {Promise<{job_id: string, status: string}>}
 */
export async function removeCaptions(fileId, { mode = 'sttn', useGpu } = {}) {
  const params = { mode };
  if (typeof useGpu === 'boolean') {
    params.use_gpu = useGpu;
  }
  const response = await apiClient.post(
    `/api/video/remove-captions/${fileId}`,
    null,
    { params }
  );
  return response.data;
}

/**
 * Poll the status of a caption removal job.
 * @param {string} jobId - Job ID returned by removeCaptions
 * @returns {Promise<{job_id: string, status: string, output_url: string|null, error: string|null}>}
 */
export async function getCaptionRemovalStatus(jobId) {
  const response = await apiClient.get(`/api/caption-removal/status/${jobId}`);
  return response.data;
}

/**
 * Detect NVIDIA GPUs available on the backend host (best-effort, via nvidia-smi).
 * @returns {Promise<{available: boolean, gpus: Array<{name: string, memory_total_mb: number|null}>, detail: string}>}
 */
export async function detectGpu() {
  const response = await apiClient.get('/api/system/gpu');
  return response.data;
}

export default apiClient;
