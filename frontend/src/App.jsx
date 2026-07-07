import { useMemo, useRef, useState } from 'react';
import VideoPlayer from './components/VideoPlayer/VideoPlayer';
import VideoUpload from './components/Upload/VideoUpload';
import RecordVideo from './components/Record/RecordVideo';
import TranscriptPanel from './components/TranscriptPanel/TranscriptPanel';
import SilenceTool from './components/EditorTools/SilenceTool';
import CaptionTool from './components/EditorTools/CaptionTool';
import EditingPlanPanel from './components/EditorTools/EditingPlanPanel';
import StockFootagePanel from './components/EditorTools/StockFootagePanel';
import SettingsModal from './components/Settings/SettingsModal';
import useSettings from './hooks/useSettings';
import {
  uploadVideo,
  importYouTubeVideo,
  getVideoURL,
  getWaveformData,
  extractWords,
  detectAudioPauses,
  createProjectEdits,
  getProjectEdits,
  updateProjectEdit,
  deleteProjectEdit,
  renderProject,
  generateEditingPlan,
  downloadStockFootage,
  getStockFootageURL,
  getAbsoluteAPIURL,
} from './services/api';
import './App.css';

function App() {
  const { settings, updateSetting } = useSettings();
  const theme = settings.theme;
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [activePanel, setActivePanel] = useState('tools');
  const [currentView, setCurrentView] = useState('editor');
  const [sourceMode, setSourceMode] = useState('choose'); // 'choose' | 'upload' | 'record'
  const [renderOptions, setRenderOptions] = useState({
    format: 'mp4',
    quality: 'high',
    saveLocation: '',
  });
  const [videoSrc, setVideoSrc] = useState(null);
  const [selectedFile, setSelectedFile] = useState(null);
  const [fileId, setFileId] = useState(null);
  const [projectId, setProjectId] = useState(null);
  const [mediaAssetId, setMediaAssetId] = useState(null);
  const [waveformData, setWaveformData] = useState(null);
  const [transcriptWords, setTranscriptWords] = useState([]);
  const [detectedPauses, setDetectedPauses] = useState([]);
  const [editOperations, setEditOperations] = useState([]);
  const [savedZoomEdits, setSavedZoomEdits] = useState([]);
  const [savedStockEdits, setSavedStockEdits] = useState([]);
  const [editingPlan, setEditingPlan] = useState([]);
  const [isGeneratingPlan, setIsGeneratingPlan] = useState(false);
  const [planError, setPlanError] = useState(null);
  const [stockDownloads, setStockDownloads] = useState({});
  const [isDownloadingStock, setIsDownloadingStock] = useState(false);
  const [stockError, setStockError] = useState(null);
  const [toolError, setToolError] = useState(null);
  const [renderResult, setRenderResult] = useState(null);
  const [currentTime, setCurrentTime] = useState(0);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [isUploading, setIsUploading] = useState(false);
  const [isLoadingWaveform, setIsLoadingWaveform] = useState(false);
  const [isLoadingTranscript, setIsLoadingTranscript] = useState(false);
  const [isDetectingSilence, setIsDetectingSilence] = useState(false);
  const [isConfirmingCuts, setIsConfirmingCuts] = useState(false);
  const [isRendering, setIsRendering] = useState(false);
  const videoPlayerRef = useRef(null);

  const rangeMarkers = useMemo(() => {
    const proposalMarkers = detectedPauses.map((pause) => ({
      ...pause,
      kind: 'proposal',
      label: `Proposed silence cut ${pause.duration.toFixed(2)}s`,
    }));
    const editMarkers = editOperations.map((edit) => ({
      id: edit.id,
      start: edit.start,
      end: edit.end,
      enabled: edit.enabled,
      kind: 'stored',
      label: `Saved cut ${(edit.end - edit.start).toFixed(2)}s`,
    }));
    return [...proposalMarkers, ...editMarkers];
  }, [detectedPauses, editOperations]);

  // Split persisted edits into cut operations and zoom operations, which are
  // tracked separately so cut markers/counts stay distinct from zoom effects.
  const applyLoadedEdits = (allEdits) => {
    const edits = allEdits || [];
    setEditOperations(edits.filter((edit) => edit.type === 'cut'));
    setSavedZoomEdits(edits.filter((edit) => edit.type === 'zoom'));
    setSavedStockEdits(
      edits.filter((edit) => edit.type === 'insert_stock_footage')
    );
  };

  // Stock-footage suggestions extracted from the current editing plan.
  const stockFootageItems = useMemo(
    () => editingPlan.filter((item) => item.feature === 'insert_stock_footage'),
    [editingPlan]
  );

  // Reset all per-project derived state before loading a new source video.
  const resetProjectStateForLoad = () => {
    setProjectId(null);
    setMediaAssetId(null);
    setWaveformData(null);
    setTranscriptWords([]);
    setDetectedPauses([]);
    setEditOperations([]);
    setSavedZoomEdits([]);
    setSavedStockEdits([]);
    setEditingPlan([]);
    setStockDownloads({});
    setStockError(null);
    setPlanError(null);
    setToolError(null);
    setRenderResult(null);
  };

  // Given a backend response carrying file_id/project_id/media_asset_id (from either a
  // direct upload or a YouTube import), point the player at the stored video and fetch
  // waveform, transcript, and saved edits. Shared by both entry points.
  const loadProjectMedia = async (response) => {
    setFileId(response.file_id);
    setProjectId(response.project_id);
    setMediaAssetId(response.media_asset_id);
    setVideoSrc(getVideoURL(response.file_id));

    setIsLoadingWaveform(true);
    setIsLoadingTranscript(true);

    const [waveform, transcript] = await Promise.all([
      getWaveformData(response.file_id, 2000),
      extractWords(response.file_id, 'base'),
    ]);

    setWaveformData(waveform.waveform);
    setTranscriptWords(transcript.words || []);
    const edits = await getProjectEdits(response.project_id);
    applyLoadedEdits(edits.edits);
  };

  const handleVideoSelect = async (file, blobUrl) => {
    // Clean up previous blob URL
    if (videoSrc && videoSrc.startsWith('blob:')) {
      URL.revokeObjectURL(videoSrc);
    }

    setSelectedFile(file);
    setVideoSrc(blobUrl);
    resetProjectStateForLoad();
    setIsUploading(true);
    setUploadProgress(0);

    try {
      // Upload video to backend
      console.log('Uploading video to backend...');
      const response = await uploadVideo(file, (progress) => {
        setUploadProgress(progress);
      });

      console.log('Video uploaded:', response);
      URL.revokeObjectURL(blobUrl);
      await loadProjectMedia(response);
    } catch (error) {
      console.error('Error uploading video or fetching data:', error);
      // Still allow playback with blob URL even if upload/waveform/transcript fails
    } finally {
      setIsUploading(false);
      setIsLoadingWaveform(false);
      setIsLoadingTranscript(false);
    }
  };

  // Import a video straight from a YouTube URL. The backend downloads it and produces the
  // same file_id/project_id/media_asset_id a direct upload would, so we reuse the pipeline.
  // Rejects on failure so the upload component can surface an inline error.
  const handleYouTubeImport = async (url, { onProgress } = {}) => {
    if (videoSrc && videoSrc.startsWith('blob:')) {
      URL.revokeObjectURL(videoSrc);
    }

    setSelectedFile({ name: 'YouTube video' });
    setVideoSrc(null);
    resetProjectStateForLoad();

    try {
      const response = await importYouTubeVideo(url, { onProgress });
      await loadProjectMedia(response);
    } catch (error) {
      console.error('Error importing YouTube video:', error);
      throw error;
    } finally {
      setIsLoadingWaveform(false);
      setIsLoadingTranscript(false);
    }
  };

  const handleTimeUpdate = (currentTime) => {
    setCurrentTime(currentTime);
  };

  const handleVideoEnded = () => {
    console.log('Video ended');
  };

  const handleSeek = (time) => {
    if (videoPlayerRef.current) {
      videoPlayerRef.current.seek(time);
    }
  };

  const handleDetectSilence = async () => {
    if (!fileId) return;

    setIsDetectingSilence(true);
    setToolError(null);
    try {
      const result = await detectAudioPauses(fileId);
      setDetectedPauses(
        (result.pauses || []).map((pause, index) => ({
          ...pause,
          id: `pause-${index}-${pause.start}-${pause.end}`,
          enabled: true,
          settings: result.settings,
        }))
      );
    } catch (error) {
      console.error('Error detecting silence:', error);
      setToolError('Could not detect silence for this video.');
    } finally {
      setIsDetectingSilence(false);
    }
  };

  const handleToggleProposedPause = (pauseId) => {
    setDetectedPauses((pauses) =>
      pauses.map((pause) =>
        pause.id === pauseId ? { ...pause, enabled: pause.enabled === false } : pause
      )
    );
  };

  const handleConfirmSilenceCuts = async () => {
    if (!projectId) return;

    const enabledPauses = detectedPauses.filter((pause) => pause.enabled !== false);
    if (enabledPauses.length === 0) return;

    setIsConfirmingCuts(true);
    setToolError(null);
    try {
      await createProjectEdits(
        projectId,
        enabledPauses.map((pause) => ({
          type: 'cut',
          source: 'silence_detection',
          start: pause.start,
          end: pause.end,
          enabled: true,
          media_asset_id: mediaAssetId,
          metadata: {
            duration: pause.duration,
            detection_settings: pause.settings,
          },
        }))
      );
      const edits = await getProjectEdits(projectId);
      applyLoadedEdits(edits.edits);
      setDetectedPauses([]);
    } catch (error) {
      console.error('Error confirming silence cuts:', error);
      setToolError('Could not save silence cuts.');
    } finally {
      setIsConfirmingCuts(false);
    }
  };

  const handleToggleStoredEdit = async (edit) => {
    if (!projectId) return;

    setToolError(null);
    try {
      const updated = await updateProjectEdit(projectId, edit.id, {
        enabled: edit.enabled === false,
      });
      setEditOperations((edits) =>
        edits.map((existing) => (existing.id === updated.id ? updated : existing))
      );
    } catch (error) {
      console.error('Error updating edit:', error);
      setToolError('Could not update the saved edit.');
    }
  };

  const handleDeleteStoredEdit = async (edit) => {
    if (!projectId) return;

    setToolError(null);
    try {
      await deleteProjectEdit(projectId, edit.id);
      setEditOperations((edits) => edits.filter((existing) => existing.id !== edit.id));
    } catch (error) {
      console.error('Error deleting edit:', error);
      setToolError('Could not remove the saved edit.');
    }
  };

  const handleGeneratePlan = async () => {
    if (!fileId) return;

    setIsGeneratingPlan(true);
    setPlanError(null);
    try {
      const result = await generateEditingPlan(fileId, 'base');
      const items = (result.editing_plan || [])
        .map((item) => ({
          id: crypto.randomUUID(),
          start: item.start ?? 0,
          end: item.end ?? 0,
          feature: item.feature,
          parameters: item.parameters || {},
        }))
        .sort((a, b) => a.start - b.start);
      setEditingPlan(items);
    } catch (error) {
      console.error('Error generating editing plan:', error);
      const detail = error.response?.data?.detail;
      setPlanError(
        detail
          ? `Could not generate an editing plan: ${detail}`
          : 'Could not generate an editing plan for this video.'
      );
    } finally {
      setIsGeneratingPlan(false);
    }
  };

  const handleUpdatePlanItem = (itemId, changes) => {
    setEditingPlan((items) =>
      items.map((item) => (item.id === itemId ? { ...item, ...changes } : item))
    );
  };

  const handleUpdatePlanItemParam = (itemId, paramName, value) => {
    setEditingPlan((items) =>
      items.map((item) =>
        item.id === itemId
          ? { ...item, parameters: { ...item.parameters, [paramName]: value } }
          : item
      )
    );
  };

  const handleDeletePlanItem = (itemId) => {
    setEditingPlan((items) => items.filter((item) => item.id !== itemId));
  };

  const handleSaveZoomEdits = async () => {
    if (!projectId) return;

    const zoomItems = editingPlan.filter((item) => item.feature === 'zoom');
    if (zoomItems.length === 0) {
      setPlanError('There are no zoom edits in the plan to save.');
      return;
    }

    setPlanError(null);
    try {
      await createProjectEdits(
        projectId,
        zoomItems.map((item) => ({
          type: 'zoom',
          source: 'editing_plan',
          start: Number(item.start) || 0,
          end: Number(item.end) || 0,
          enabled: true,
          media_asset_id: mediaAssetId,
          metadata: {
            zoom_level: Number(item.parameters?.zoom_level) || 1.2,
          },
        }))
      );
      const edits = await getProjectEdits(projectId);
      applyLoadedEdits(edits.edits);
      // Clear saved zoom items from the working plan to avoid re-saving them.
      setEditingPlan((items) => items.filter((item) => item.feature !== 'zoom'));
    } catch (error) {
      console.error('Error saving zoom edits:', error);
      setPlanError('Could not save zoom edits to the project.');
    }
  };

  const handleDownloadStockFootage = async () => {
    if (stockFootageItems.length === 0) return;

    setIsDownloadingStock(true);
    setStockError(null);
    // Mark every clip as queued so the UI shows progress immediately.
    setStockDownloads((current) => {
      const next = { ...current };
      stockFootageItems.forEach((item) => {
        next[item.id] = { ...next[item.id], status: 'loading' };
      });
      return next;
    });

    let anyFailed = false;
    for (const item of stockFootageItems) {
      const query = item.parameters?.search_query?.trim();
      if (!query) {
        setStockDownloads((current) => ({
          ...current,
          [item.id]: { status: 'error', error: 'No search query for this clip.' },
        }));
        anyFailed = true;
        continue;
      }

      try {
        const result = await downloadStockFootage(query);
        const filename = result.file_path.split('/').pop();
        setStockDownloads((current) => ({
          ...current,
          [item.id]: {
            status: 'done',
            filename,
            filePath: result.file_path,
            previewUrl: getStockFootageURL(filename),
            searchQuery: query,
          },
        }));
      } catch (error) {
        console.error('Error downloading stock footage:', error);
        anyFailed = true;
        setStockDownloads((current) => ({
          ...current,
          [item.id]: {
            status: 'error',
            error: error.response?.data?.detail || 'Download failed.',
          },
        }));
      }
    }

    if (anyFailed) {
      setStockError('Some clips could not be downloaded. See each card for details.');
    }
    setIsDownloadingStock(false);
  };

  const handleSaveStockEdits = async () => {
    if (!projectId) return;

    // Only save clips that downloaded successfully, carrying the exact file
    // so render reuses the previewed clip instead of fetching a new random one.
    const ready = stockFootageItems.filter(
      (item) => stockDownloads[item.id]?.status === 'done'
    );
    if (ready.length === 0) {
      setStockError('Download at least one clip before saving.');
      return;
    }

    setStockError(null);
    try {
      await createProjectEdits(
        projectId,
        ready.map((item) => {
          const download = stockDownloads[item.id];
          return {
            type: 'insert_stock_footage',
            source: 'editing_plan',
            start: Number(item.start) || 0,
            end: Number(item.end) || 0,
            enabled: true,
            media_asset_id: mediaAssetId,
            metadata: {
              search_query: download.searchQuery,
              footage_path: download.filePath,
            },
          };
        })
      );
      const edits = await getProjectEdits(projectId);
      applyLoadedEdits(edits.edits);
      // Drop saved suggestions from the working plan to avoid re-saving them.
      const savedIds = new Set(ready.map((item) => item.id));
      setEditingPlan((items) => items.filter((item) => !savedIds.has(item.id)));
      setStockDownloads((current) => {
        const next = { ...current };
        savedIds.forEach((id) => delete next[id]);
        return next;
      });
    } catch (error) {
      console.error('Error saving stock footage edits:', error);
      setStockError('Could not save stock footage edits to the project.');
    }
  };

  const handleRenderProject = async () => {
    if (!projectId) return;

    setIsRendering(true);
    setToolError(null);
    try {
      const result = await renderProject(projectId);
      setRenderResult({
        filename: result.filename,
        url: getAbsoluteAPIURL(result.output_url),
        appliedEdits: result.applied_edits,
      });
    } catch (error) {
      console.error('Error rendering project:', error);
      setToolError('Could not render the project.');
    } finally {
      setIsRendering(false);
    }
  };

  const handleGoToRender = () => {
    setCurrentView('render');
  };

  const handleBackToEditor = () => {
    setCurrentView('editor');
  };

  const resetProjectState = () => {
    if (videoSrc?.startsWith('blob:')) {
      URL.revokeObjectURL(videoSrc);
    }
    setVideoSrc(null);
    setSelectedFile(null);
    setFileId(null);
    setProjectId(null);
    setMediaAssetId(null);
    setWaveformData(null);
    setTranscriptWords([]);
    setDetectedPauses([]);
    setEditOperations([]);
    setSavedZoomEdits([]);
    setSavedStockEdits([]);
    setEditingPlan([]);
    setStockDownloads({});
    setStockError(null);
    setPlanError(null);
    setToolError(null);
    setRenderResult(null);
    setCurrentView('editor');
    setSourceMode('choose');
  };

  const renderEditor = () => (
    <main className="app-main">
      {!videoSrc ? (
        <div className="upload-view">
          {sourceMode === 'choose' ? (
            <div className="source-chooser">
              <h2>Start a new project</h2>
              <p>Bring in footage to edit — upload an existing file or record one now.</p>
              <div className="source-options">
                <button
                  type="button"
                  className="source-card"
                  onClick={() => setSourceMode('upload')}
                >
                  <svg width="40" height="40" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M9 16h6v-6h4l-7-7-7 7h4zm-4 2h14v2H5z" />
                  </svg>
                  <strong>Upload footage</strong>
                  <span>Use a video file from your computer or a YouTube link</span>
                </button>
                <button
                  type="button"
                  className="source-card"
                  onClick={() => setSourceMode('record')}
                >
                  <svg width="40" height="40" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M17 10.5V7a1 1 0 0 0-1-1H4a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-3.5l4 4v-11l-4 4z" />
                  </svg>
                  <strong>Record new footage</strong>
                  <span>Capture video with your camera and microphone</span>
                </button>
              </div>
            </div>
          ) : (
            <div className="source-panel">
              <button
                type="button"
                className="text-button source-back"
                onClick={() => setSourceMode('choose')}
              >
                ← Back
              </button>
              {sourceMode === 'upload' ? (
                <VideoUpload
                  onVideoSelect={handleVideoSelect}
                  onYouTubeImport={handleYouTubeImport}
                />
              ) : (
                <RecordVideo onVideoSelect={handleVideoSelect} />
              )}
            </div>
          )}
        </div>
      ) : (
        <div className="workspace">
          <section className="player-section">
            <VideoPlayer
              ref={videoPlayerRef}
              src={videoSrc}
              onTimeUpdate={handleTimeUpdate}
              onEnded={handleVideoEnded}
              waveformData={waveformData}
              rangeMarkers={rangeMarkers}
            />

            <div className="status-strip">
              <div>
                <span className="status-label">Source</span>
                <strong>{selectedFile?.name}</strong>
              </div>
              {isUploading && <span>Uploading {uploadProgress}%</span>}
              {isLoadingWaveform && <span>Generating waveform...</span>}
              {isLoadingTranscript && <span>Extracting transcript...</span>}
              <button className="text-button" onClick={resetProjectState}>
                Change Video
              </button>
            </div>
          </section>

          <aside className="side-panel">
            <div className="panel-tabs">
              <button
                type="button"
                className={activePanel === 'tools' ? 'active' : ''}
                onClick={() => setActivePanel('tools')}
              >
                Tools
              </button>
              <button
                type="button"
                className={activePanel === 'plan' ? 'active' : ''}
                onClick={() => setActivePanel('plan')}
              >
                Plan
              </button>
              <button
                type="button"
                className={activePanel === 'stock' ? 'active' : ''}
                onClick={() => setActivePanel('stock')}
              >
                Stock Footage
              </button>
              <button
                type="button"
                className={activePanel === 'transcript' ? 'active' : ''}
                onClick={() => setActivePanel('transcript')}
              >
                Transcript
              </button>
            </div>

            <div className="panel-content">
              {activePanel === 'tools' && (
                <SilenceTool
                  detectedPauses={detectedPauses}
                  editOperations={editOperations}
                  renderResult={renderResult}
                  loading={{
                    detecting: isDetectingSilence,
                    confirming: isConfirmingCuts,
                    rendering: isRendering,
                  }}
                  error={toolError}
                  onDetect={handleDetectSilence}
                  onToggleProposal={handleToggleProposedPause}
                  onConfirm={handleConfirmSilenceCuts}
                  onToggleEdit={handleToggleStoredEdit}
                  onDeleteEdit={handleDeleteStoredEdit}
                  onRender={handleGoToRender}
                  onSeek={handleSeek}
                />
              )}
              {activePanel === 'tools' && (
                <CaptionTool key={fileId} fileId={fileId} useGpu={settings.useGpu} />
              )}
              {activePanel === 'plan' && (
                <EditingPlanPanel
                  plan={editingPlan}
                  loading={isGeneratingPlan}
                  error={planError}
                  hasVideo={Boolean(fileId)}
                  onGenerate={handleGeneratePlan}
                  onUpdateItem={handleUpdatePlanItem}
                  onUpdateItemParam={handleUpdatePlanItemParam}
                  onDeleteItem={handleDeletePlanItem}
                  onSaveZoomEdits={handleSaveZoomEdits}
                  savedZoomCount={savedZoomEdits.length}
                />
              )}
              {activePanel === 'stock' && (
                <StockFootagePanel
                  items={stockFootageItems}
                  downloads={stockDownloads}
                  planReady={editingPlan.length > 0 || savedStockEdits.length > 0}
                  isDownloading={isDownloadingStock}
                  error={stockError}
                  onDownloadAll={handleDownloadStockFootage}
                  onSaveToProject={handleSaveStockEdits}
                  onSeek={handleSeek}
                  savedStockCount={savedStockEdits.length}
                />
              )}
              {activePanel === 'transcript' && (
                <TranscriptPanel
                  words={transcriptWords}
                  currentTime={currentTime}
                  onSeek={handleSeek}
                  loading={isLoadingTranscript}
                />
              )}
            </div>
          </aside>
        </div>
      )}
    </main>
  );

  const renderRenderPage = () => (
    <main className="render-page">
      <section className="render-options">
        <div className="render-heading">
          <button type="button" className="text-button" onClick={handleBackToEditor}>
            Back to Editor
          </button>
          <div>
            <h2>Final Render</h2>
            <p>Choose export settings before rendering the saved edit stack.</p>
          </div>
        </div>

        <div className="render-grid">
          <label>
            Format
            <select
              value={renderOptions.format}
              onChange={(event) =>
                setRenderOptions((options) => ({ ...options, format: event.target.value }))
              }
            >
              <option value="mp4">MP4</option>
              <option value="mov">MOV</option>
              <option value="webm">WebM</option>
            </select>
          </label>

          <label>
            Quality
            <select
              value={renderOptions.quality}
              onChange={(event) =>
                setRenderOptions((options) => ({ ...options, quality: event.target.value }))
              }
            >
              <option value="high">High</option>
              <option value="medium">Medium</option>
              <option value="draft">Draft</option>
            </select>
          </label>

          <label className="wide-field">
            Save location path
            <input
              value={renderOptions.saveLocation}
              placeholder="Default: temp/outputs"
              onChange={(event) =>
                setRenderOptions((options) => ({
                  ...options,
                  saveLocation: event.target.value,
                }))
              }
            />
          </label>
        </div>

        <div className="render-summary">
          <span>{editOperations.filter((edit) => edit.enabled !== false).length} active cuts</span>
          <span>{savedZoomEdits.filter((edit) => edit.enabled !== false).length} zoom effects</span>
          <span>{savedStockEdits.filter((edit) => edit.enabled !== false).length} stock clips</span>
          <span>{selectedFile?.name || 'No video selected'}</span>
        </div>

        <button
          type="button"
          className="render-submit"
          onClick={handleRenderProject}
          disabled={
            isRendering ||
            !projectId ||
            (editOperations.length === 0 &&
              savedZoomEdits.length === 0 &&
              savedStockEdits.length === 0)
          }
        >
          {isRendering ? 'Rendering...' : 'Render Video'}
        </button>

        {toolError && <div className="render-error">{toolError}</div>}

        {renderResult && (
          <a className="render-download" href={renderResult.url} target="_blank" rel="noreferrer">
            Download {renderResult.filename}
          </a>
        )}
      </section>
    </main>
  );

  return (
    <div className={`app ${theme === 'dark' ? 'dark' : 'light'}`}>
      <header className="top-bar">
        <div>
          <h1>Video Editor</h1>
          <span>{projectId ? `Project ${projectId}` : 'No project loaded'}</span>
        </div>
        <button
          type="button"
          className="settings-button"
          onClick={() => setSettingsOpen(true)}
          aria-label="Open settings"
        >
          ⚙ Settings
        </button>
      </header>

      {currentView === 'render' ? renderRenderPage() : renderEditor()}

      {settingsOpen && (
        <SettingsModal
          onClose={() => setSettingsOpen(false)}
          settings={settings}
          updateSetting={updateSetting}
        />
      )}
    </div>
  );
}

export default App;
