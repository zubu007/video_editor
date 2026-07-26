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
 * Suggest animated diagram overlays for an uploaded video's transcript
 * @param {string} fileId - File ID
 * @param {string} modelSize - Whisper model size
 * @param {string} additionalContext - Additional context for AI
 * @returns {Promise<{diagrams: Array}>}
 */
export async function suggestDiagrams(fileId, modelSize = 'base', additionalContext = '') {
  const response = await apiClient.post(`/api/diagrams/suggest/${fileId}`, {
    model_size: modelSize,
    additional_context: additionalContext,
  });

  return response.data;
}

/**
 * Render one diagram suggestion to a preview video (Manim, cached server-side)
 * @param {Object} suggestion - Diagram suggestion with diagram_type, title, start, end, graph
 *   and an optional layout ('landscape' | 'portrait')
 * @returns {Promise<{video_url: string, filename: string, cached: boolean}>}
 */
export async function renderDiagramPreview(suggestion) {
  const response = await apiClient.post('/api/diagrams/render', {
    diagram_type: suggestion.diagram_type,
    title: suggestion.title || '',
    start: suggestion.start,
    end: suggestion.end,
    graph: suggestion.graph,
    layout: suggestion.layout || 'landscape',
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
      padding: settings.padding ?? 0.1,
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
 * Download stock B-roll from Pexels for a search query.
 * @param {string} searchTerm - Search query (e.g. 'ocean waves')
 * @param {string} quality - Video quality (hd, sd, original); ignored for images
 * @param {string} mediaType - 'video' for a short clip, 'image' for a still photo
 * @returns {Promise<{file_path: string, search_term: string, media_type: string}>}
 */
export async function downloadStockFootage(searchTerm, quality = 'hd', mediaType = 'video') {
  const formData = new FormData();
  formData.append('search_term', searchTerm);
  formData.append('quality', quality);
  formData.append('media_type', mediaType);
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
 * Start a background render of a project's enabled edits.
 * Rendering runs asynchronously; poll getRenderStatus(jobId) for progress and the result.
 * @param {string} projectId - Project ID
 * @returns {Promise<{job_id: string, status: string}>}
 */
export async function renderProject(projectId) {
  const response = await apiClient.post(`/api/projects/${projectId}/render`);
  return response.data;
}

/**
 * Poll the status of a render job.
 * @param {string} jobId - Job ID returned by renderProject
 * @returns {Promise<{job_id: string, status: string, progress: number,
 *   output_url: string|null, filename: string|null, applied_edits: number|null,
 *   error: string|null}>}
 */
export async function getRenderStatus(jobId) {
  const response = await apiClient.get(`/api/render/status/${jobId}`);
  return response.data;
}

/**
 * Fetch a project's ordered timeline segments
 * @param {string} projectId - Project ID
 * @returns {Promise<{segments: Array<{id: string, start: number, end: number, position: number}>}>}
 */
export async function getProjectTimeline(projectId) {
  const response = await apiClient.get(`/api/projects/${projectId}/timeline`);
  return response.data;
}

/**
 * Replace a project's ordered timeline segments.
 * The array order is the playback order; an empty array clears the timeline.
 * @param {string} projectId - Project ID
 * @param {Array<{start: number, end: number}>} segments - Ordered source ranges
 * @param {string|null} mediaAssetId - Media asset the segments reference
 * @returns {Promise<{segments: Array<{id: string, start: number, end: number, position: number}>}>}
 */
export async function saveProjectTimeline(projectId, segments, mediaAssetId = null) {
  const response = await apiClient.put(`/api/projects/${projectId}/timeline`, {
    segments: segments.map(({ start, end }) => ({ start, end })),
    media_asset_id: mediaAssetId,
  });
  return response.data;
}

/**
 * List the caption style presets available for burned-in captions.
 * @returns {Promise<{styles: Array<{name: string, font_family: string, font_scale: number,
 *   text_colour: string, highlight_colour: string|null, outline_colour: string,
 *   outline_scale: number, shadow_scale: number, margin_v_scale: number,
 *   word_colours: string[], uppercase: boolean, pop_scale: number|null,
 *   max_words_per_line: number}>, default_style: string}>}
 */
export async function getCaptionStyles() {
  const response = await apiClient.get('/api/captions/styles');
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
 * Start a background job that imports a single video from YouTube.
 * @param {string} url - YouTube video URL
 * @param {{ projectId?: string, projectName?: string }} [options]
 * @returns {Promise<{job_id: string, status: string}>}
 */
export async function downloadYouTube(url, { projectId, projectName } = {}) {
  const response = await apiClient.post('/api/video/download-youtube', {
    url,
    project_id: projectId ?? null,
    project_name: projectName ?? null,
  });
  return response.data;
}

/**
 * Poll the status of a YouTube download job.
 * @param {string} jobId - Job ID returned by downloadYouTube
 * @returns {Promise<{job_id: string, status: string, progress: number, file_id: string|null, project_id: string|null, media_asset_id: string|null, error: string|null}>}
 */
export async function getYoutubeDownloadStatus(jobId) {
  const response = await apiClient.get(`/api/youtube-download/status/${jobId}`);
  return response.data;
}

/**
 * Start a YouTube download and resolve once it finishes (or rejects on error).
 * @param {string} url - YouTube video URL
 * @param {{ projectName?: string, onProgress?: (fraction: number) => void, intervalMs?: number }} [options]
 * @returns {Promise<{file_id: string, project_id: string, media_asset_id: string}>}
 */
export async function importYouTubeVideo(
  url,
  { projectName, onProgress, intervalMs = 1500 } = {}
) {
  const { job_id } = await downloadYouTube(url, { projectName });

  return new Promise((resolve, reject) => {
    const poll = async () => {
      try {
        const status = await getYoutubeDownloadStatus(job_id);
        if (onProgress && typeof status.progress === 'number') {
          onProgress(status.progress);
        }
        if (status.status === 'done') {
          resolve(status);
        } else if (status.status === 'error') {
          reject(new Error(status.error || 'YouTube download failed'));
        } else {
          setTimeout(poll, intervalMs);
        }
      } catch (err) {
        reject(err);
      }
    };
    poll();
  });
}

/**
 * Ask the project assistant a question about the current project.
 * @param {string} projectId - Project ID
 * @param {Array<{role: string, content: string}>} messages - Conversation history
 *   (user/assistant turns, oldest first, ending with the new user message)
 * @param {{ transcript?: string, activityLog?: string[] }} [context] - Project context:
 *   plain-text transcript and recent editor activity lines
 * @returns {Promise<{reply: string}>}
 */
export async function sendProjectChat(projectId, messages, { transcript = '', activityLog = [] } = {}) {
  const response = await apiClient.post(`/api/projects/${projectId}/chat`, {
    messages,
    transcript,
    activity_log: activityLog,
  });
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
