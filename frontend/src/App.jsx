import { useEffect, useMemo, useRef, useState } from 'react';
import VideoPlayer from './components/VideoPlayer/VideoPlayer';
import VideoUpload from './components/Upload/VideoUpload';
import RecordVideo from './components/Record/RecordVideo';
import TranscriptPanel from './components/TranscriptPanel/TranscriptPanel';
import Timeline from './components/Timeline/Timeline';
import SilenceTool from './components/EditorTools/SilenceTool';
import CaptionTool from './components/EditorTools/CaptionTool';
import CaptionsPanel from './components/EditorTools/CaptionsPanel';
import TextCaptionsPanel from './components/EditorTools/TextCaptionsPanel';
import EditingPlanPanel from './components/EditorTools/EditingPlanPanel';
import EditsPanel from './components/EditorTools/EditsPanel';
import StockFootagePanel from './components/EditorTools/StockFootagePanel';
import DiagramPanel from './components/EditorTools/DiagramPanel';
import DeathCutsPanel from './components/EditorTools/DeathCutsPanel';
import HighlightsPanel from './components/EditorTools/HighlightsPanel';
import ChatPanel from './components/Assistant/ChatPanel';
import InspectorPanel from './components/Inspector/InspectorPanel';
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
  getRenderStatus,
  getProjectTimeline,
  saveProjectTimeline,
  generateEditingPlan,
  suggestDiagrams,
  renderDiagramPreview,
  downloadStockFootage,
  getStockFootageURL,
  getAbsoluteAPIURL,
  getCaptionStyles,
  sendProjectChat,
  getSlotPreview,
  startDeathDetection,
  getDeathDetectionStatus,
  createHighlightClip,
} from './services/api';
import './App.css';

// How often to poll a running render job for progress.
const RENDER_POLL_INTERVAL_MS = 1000;
// How often to poll a running death-detection job.
const DEATH_POLL_INTERVAL_MS = 2000;

function App() {
  const { settings, updateSetting } = useSettings();
  const theme = settings.theme;
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [activePanel, setActivePanel] = useState('tools');
  const [currentView, setCurrentView] = useState('editor');
  const [sourceMode, setSourceMode] = useState('choose'); // 'choose' | 'upload' | 'record' | 'youtube' | 'gaming'
  // True when the project was started via "Edit a gaming video" — surfaces the
  // Dota 2 "Deaths" tab.
  const [isGaming, setIsGaming] = useState(false);
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
  const [sourceDuration, setSourceDuration] = useState(null);
  const [timelineSegments, setTimelineSegments] = useState([]);
  const [timelineDirty, setTimelineDirty] = useState(false);
  const [hasSavedTimeline, setHasSavedTimeline] = useState(false);
  const [isSavingTimeline, setIsSavingTimeline] = useState(false);
  const [transcriptWords, setTranscriptWords] = useState([]);
  const [detectedPauses, setDetectedPauses] = useState([]);
  const [editOperations, setEditOperations] = useState([]);
  const [savedZoomEdits, setSavedZoomEdits] = useState([]);
  const [savedStockEdits, setSavedStockEdits] = useState([]);
  const [savedDiagramEdits, setSavedDiagramEdits] = useState([]);
  // Burned-in caption presets fetched once from the backend, the user's
  // current pick in the Captions tab, and the saved captions edit (if any).
  const [captionStyles, setCaptionStyles] = useState([]);
  const [captionStyleName, setCaptionStyleName] = useState(null);
  const [captionWordsPerLine, setCaptionWordsPerLine] = useState(null);
  const [savedCaptionsEdits, setSavedCaptionsEdits] = useState([]);
  const [isSavingCaptions, setIsSavingCaptions] = useState(false);
  const [captionsError, setCaptionsError] = useState(null);
  // Hand-written streaming captions ("Notes"): saved text_caption edits placed
  // at the playhead, plus their save/error state.
  const [savedTextCaptions, setSavedTextCaptions] = useState([]);
  const [isSavingTextCaption, setIsSavingTextCaption] = useState(false);
  const [textCaptionsError, setTextCaptionsError] = useState(null);
  const [editingPlan, setEditingPlan] = useState([]);
  const [isGeneratingPlan, setIsGeneratingPlan] = useState(false);
  const [planError, setPlanError] = useState(null);
  const [diagramSuggestions, setDiagramSuggestions] = useState([]);
  const [isSuggestingDiagrams, setIsSuggestingDiagrams] = useState(false);
  const [diagramError, setDiagramError] = useState(null);
  const [savingDiagramId, setSavingDiagramId] = useState(null);
  // Per-suggestion motion-diagram previews: {[suggestionId]: {status, url, error}}.
  const [diagramPreviews, setDiagramPreviews] = useState({});
  // Source video aspect ratio (width / height), reported by the player once
  // metadata loads; portrait sources default new diagrams to portrait layout.
  const [videoAspectRatio, setVideoAspectRatio] = useState(null);
  // Timeline selection driving the inspector: {kind: 'segment'|'overlay', id}.
  const [inspected, setInspected] = useState(null);
  // Per-overlay status of stock footage re-downloads started from the inspector.
  const [stockRefetch, setStockRefetch] = useState({});
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
  // Render progress as a 0.0–1.0 fraction while a background render job runs.
  const [renderProgress, setRenderProgress] = useState(0);
  // Assistant chat feed: 'log' entries (editor activity) interleaved with
  // 'user'/'assistant' conversation turns.
  const [chatMessages, setChatMessages] = useState([]);
  const [isChatSending, setIsChatSending] = useState(false);
  const [chatError, setChatError] = useState(null);
  // Dota 2 death detection: team, job status, detected intervals, the resolved
  // slot + confidence, and the manual slot-selector state (thumbnails + override).
  const [deathTeam, setDeathTeam] = useState('radiant');
  const [deathStatus, setDeathStatus] = useState('idle'); // idle|loading-slots|detecting|done|error
  const [deathError, setDeathError] = useState(null);
  const [deathIntervals, setDeathIntervals] = useState([]);
  const [deathPlayerSlot, setDeathPlayerSlot] = useState(null);
  const [deathConfidence, setDeathConfidence] = useState(null);
  const [deathSlots, setDeathSlots] = useState([]);
  const [deathSelectedSlot, setDeathSelectedSlot] = useState(null);
  const [deathCutsSaved, setDeathCutsSaved] = useState(0);
  // K/D/A event markers for the play bar (gaming mode), placed by the dedicated
  // "Detect K/D/A markers" button.
  const [gamingEvents, setGamingEvents] = useState([]);
  const [markerStatus, setMarkerStatus] = useState('idle'); // idle|detecting|done|error
  const [markerError, setMarkerError] = useState(null);
  // "Highlights" tab: trim a quick clip between two source timestamps.
  const [highlightStart, setHighlightStart] = useState('');
  const [highlightEnd, setHighlightEnd] = useState('');
  const [highlightStatus, setHighlightStatus] = useState('idle'); // idle|creating|done|error
  const [highlightError, setHighlightError] = useState(null);
  const [highlightResult, setHighlightResult] = useState(null);
  const videoPlayerRef = useRef(null);
  const deathPollRef = useRef(null);
  const markerPollRef = useRef(null);
  // Holds the setInterval id for polling the active render job's status.
  const renderPollRef = useRef(null);

  // Append an editor-activity note to the assistant feed (readable log line).
  const logActivity = (content) => {
    setChatMessages((messages) => [
      ...messages,
      {
        id: crypto.randomUUID(),
        role: 'log',
        content,
        time: new Date().toLocaleTimeString([], {
          hour: '2-digit',
          minute: '2-digit',
        }),
      },
    ]);
  };

  // Timeline preview playback reads segments via a ref so the media-element
  // event handlers never act on a stale segment list.
  const timelineRef = useRef([]);
  const activeSegmentIndexRef = useRef(0);
  useEffect(() => {
    timelineRef.current = timelineSegments;
    if (activeSegmentIndexRef.current >= timelineSegments.length) {
      activeSegmentIndexRef.current = 0;
    }
  }, [timelineSegments]);

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
    setSavedDiagramEdits(edits.filter((edit) => edit.type === 'diagram'));
    const captionsEdits = edits.filter((edit) => edit.type === 'captions');
    setSavedCaptionsEdits(captionsEdits);
    setSavedTextCaptions(edits.filter((edit) => edit.type === 'text_caption'));
    // Adopt the saved captions settings so the panel and live preview match.
    if (captionsEdits[0]?.metadata?.style) {
      setCaptionStyleName(captionsEdits[0].metadata.style);
      setCaptionWordsPerLine(captionsEdits[0].metadata.max_words_per_line ?? null);
    }
  };

  // Load the caption style presets once; the default becomes the initial pick.
  useEffect(() => {
    let cancelled = false;
    getCaptionStyles()
      .then((data) => {
        if (cancelled) return;
        setCaptionStyles(data.styles);
        setCaptionStyleName((current) => current || data.default_style);
      })
      .catch((error) => {
        console.error('Error loading caption styles:', error);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Overlay edits shown as movable clips on the timeline's overlay lanes.
  const timelineOverlays = useMemo(
    () => [...savedZoomEdits, ...savedStockEdits, ...savedDiagramEdits],
    [savedZoomEdits, savedStockEdits, savedDiagramEdits]
  );

  // Any saved edit (cut, zoom, stock, diagram, captions) or a custom timeline
  // makes the project renderable — the render endpoint supports each alone.
  const hasRenderableContent =
    editOperations.length > 0 ||
    timelineOverlays.length > 0 ||
    savedCaptionsEdits.length > 0 ||
    savedTextCaptions.length > 0 ||
    hasSavedTimeline;

  // Live caption preview on the player: while the Captions tab is open it
  // tracks the user's current pick; otherwise it reflects the saved captions
  // edit (if enabled). The exact look is burned server-side at render time.
  const captionPreview = useMemo(() => {
    if (transcriptWords.length === 0 || captionStyles.length === 0) return null;
    const saved = savedCaptionsEdits.find((edit) => edit.enabled !== false);
    const previewing = activePanel === 'captions';
    const styleName = previewing
      ? captionStyleName
      : saved
        ? saved.metadata?.style || captionStyleName
        : null;
    const style = captionStyles.find((entry) => entry.name === styleName);
    if (!style) return null;
    return {
      words: transcriptWords,
      style,
      wordsPerLine: previewing
        ? captionWordsPerLine
        : (saved?.metadata?.max_words_per_line ?? null),
    };
  }, [
    transcriptWords,
    captionStyles,
    savedCaptionsEdits,
    activePanel,
    captionStyleName,
    captionWordsPerLine,
  ]);

  // Stock-footage suggestions extracted from the current editing plan.
  const stockFootageItems = useMemo(
    () => editingPlan.filter((item) => item.feature === 'insert_stock_footage'),
    [editingPlan]
  );

  // Resolve the inspected id against current state so the inspector always
  // shows live values and closes itself when the item is deleted.
  const inspectorSelection = useMemo(() => {
    if (!inspected) return null;
    if (inspected.kind === 'segment') {
      const index = timelineSegments.findIndex(
        (segment) => segment.id === inspected.id
      );
      if (index === -1) return null;
      return { kind: 'segment', segment: timelineSegments[index], index };
    }
    const overlay = timelineOverlays.find((entry) => entry.id === inspected.id);
    return overlay ? { kind: 'overlay', overlay } : null;
  }, [inspected, timelineSegments, timelineOverlays]);

  const handleSelectSegment = (segmentId) => {
    if (segmentId) {
      setInspected({ kind: 'segment', id: segmentId });
    } else {
      setInspected((current) => (current?.kind === 'segment' ? null : current));
    }
  };

  const handleSelectOverlay = (overlayId) => {
    if (overlayId) {
      setInspected({ kind: 'overlay', id: overlayId });
    } else {
      setInspected((current) => (current?.kind === 'overlay' ? null : current));
    }
  };

  // Reset all per-project derived state before loading a new source video.
  const resetProjectStateForLoad = () => {
    // Drop any in-flight render poll first: it belongs to the outgoing project
    // and would otherwise keep polling a stale job, then inject that project's
    // result into this one when it finishes.
    stopRenderPolling();
    setIsRendering(false);
    setRenderProgress(0);
    setProjectId(null);
    setMediaAssetId(null);
    setWaveformData(null);
    setSourceDuration(null);
    setTimelineSegments([]);
    setTimelineDirty(false);
    setHasSavedTimeline(false);
    activeSegmentIndexRef.current = 0;
    setTranscriptWords([]);
    setDetectedPauses([]);
    setEditOperations([]);
    setSavedZoomEdits([]);
    setSavedStockEdits([]);
    setSavedDiagramEdits([]);
    setSavedCaptionsEdits([]);
    setCaptionsError(null);
    setSavedTextCaptions([]);
    setTextCaptionsError(null);
    setEditingPlan([]);
    setDiagramSuggestions([]);
    setDiagramError(null);
    setSavingDiagramId(null);
    setVideoAspectRatio(null);
    setInspected(null);
    setStockRefetch({});
    setStockDownloads({});
    setStockError(null);
    setPlanError(null);
    setToolError(null);
    setRenderResult(null);
    setChatMessages([]);
    setChatError(null);
    setDeathStatus('idle');
    setDeathError(null);
    setDeathIntervals([]);
    setDeathPlayerSlot(null);
    setDeathConfidence(null);
    setDeathSlots([]);
    setDeathSelectedSlot(null);
    setDeathCutsSaved(0);
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
    setSourceDuration(waveform.duration);
    setTranscriptWords(transcript.words || []);
    logActivity(
      `Video loaded (${waveform.duration.toFixed(1)}s). Transcript extracted with ${
        (transcript.words || []).length
      } words.`
    );
    const edits = await getProjectEdits(response.project_id);
    applyLoadedEdits(edits.edits);
    if ((edits.edits || []).length > 0) {
      logActivity(`Restored ${edits.edits.length} saved edits from the project.`);
    }

    // Restore a saved timeline arrangement, or start from the full source as
    // a single segment.
    const timeline = await getProjectTimeline(response.project_id);
    if (timeline.segments.length > 0) {
      setTimelineSegments(
        timeline.segments.map(({ id, start, end }) => ({ id, start, end }))
      );
      setHasSavedTimeline(true);
    } else {
      setTimelineSegments([
        { id: crypto.randomUUID(), start: 0, end: waveform.duration },
      ]);
      setHasSavedTimeline(false);
    }
    setTimelineDirty(false);
    activeSegmentIndexRef.current = 0;
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

  const handleTimeUpdate = (time) => {
    setCurrentTime(time);

    // Sequential timeline preview: when playback reaches the end of the
    // active segment, jump to the next segment in timeline order (which may
    // be anywhere in the source), pausing after the last one.
    const segments = timelineRef.current;
    if (segments.length === 0) return;

    const EPSILON = 0.08;
    let index = activeSegmentIndexRef.current;
    if (index >= segments.length) index = 0;
    const segment = segments[index];

    if (time >= segment.start - EPSILON && time < segment.end - EPSILON) {
      return;
    }

    if (time >= segment.end - EPSILON && time < segment.end + 0.5) {
      if (index + 1 < segments.length) {
        activeSegmentIndexRef.current = index + 1;
        videoPlayerRef.current?.seek(segments[index + 1].start);
      } else {
        videoPlayerRef.current?.pause();
      }
      return;
    }

    // The user seeked elsewhere: re-sync to the segment containing that time.
    const containing = segments.findIndex(
      (candidate) => time >= candidate.start && time < candidate.end
    );
    if (containing !== -1) {
      activeSegmentIndexRef.current = containing;
    }
  };

  const MIN_SEGMENT_LENGTH = 0.1;

  const handleSplitAtPlayhead = () => {
    const time = currentTime;
    const index = timelineSegments.findIndex(
      (segment) =>
        time > segment.start + MIN_SEGMENT_LENGTH &&
        time < segment.end - MIN_SEGMENT_LENGTH
    );
    if (index === -1) return;

    const segment = timelineSegments[index];
    const next = [...timelineSegments];
    next.splice(
      index,
      1,
      { ...segment, id: crypto.randomUUID(), end: time },
      { ...segment, id: crypto.randomUUID(), start: time }
    );
    setTimelineSegments(next);
    setTimelineDirty(true);
  };

  const handleReorderSegments = (fromIndex, insertIndex) => {
    if (fromIndex === insertIndex || fromIndex + 1 === insertIndex) return;
    const next = [...timelineSegments];
    const [moved] = next.splice(fromIndex, 1);
    next.splice(insertIndex > fromIndex ? insertIndex - 1 : insertIndex, 0, moved);
    setTimelineSegments(next);
    setTimelineDirty(true);
  };

  const handleDeleteSegment = (segmentId) => {
    if (timelineSegments.length <= 1) return;
    setTimelineSegments(
      timelineSegments.filter((segment) => segment.id !== segmentId)
    );
    setTimelineDirty(true);
  };

  // Trim a segment's source range from the inspector's numeric fields.
  const handleUpdateSegment = (segmentId, changes) => {
    setTimelineSegments((segments) =>
      segments.map((segment) =>
        segment.id === segmentId ? { ...segment, ...changes } : segment
      )
    );
    setTimelineDirty(true);
  };

  const handleResetTimeline = () => {
    if (!sourceDuration) return;
    setTimelineSegments([
      { id: crypto.randomUUID(), start: 0, end: sourceDuration },
    ]);
    setTimelineDirty(true);
  };

  const handleSaveTimeline = async () => {
    if (!projectId) return;

    setIsSavingTimeline(true);
    setToolError(null);
    try {
      // A single untouched full-length segment means "no custom timeline";
      // save an empty list so render falls back to the plain cut flow.
      const isTrivial =
        timelineSegments.length === 1 &&
        timelineSegments[0].start === 0 &&
        sourceDuration !== null &&
        Math.abs(timelineSegments[0].end - sourceDuration) < 0.01;

      const result = await saveProjectTimeline(
        projectId,
        isTrivial ? [] : timelineSegments,
        mediaAssetId
      );
      if (result.segments.length > 0) {
        setTimelineSegments(
          result.segments.map(({ id, start, end }) => ({ id, start, end }))
        );
        setHasSavedTimeline(true);
      } else {
        setHasSavedTimeline(false);
      }
      setTimelineDirty(false);
      logActivity(
        result.segments.length > 0
          ? `Timeline saved with ${result.segments.length} segments.`
          : 'Timeline reset to the original order.'
      );
    } catch (error) {
      console.error('Error saving timeline:', error);
      setToolError('Could not save the timeline.');
    } finally {
      setIsSavingTimeline(false);
    }
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
      logActivity(
        `Silence detection found ${result.count} pauses (${(
          result.total_silence_duration || 0
        ).toFixed(1)}s of silence).`
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
      logActivity(`Saved ${enabledPauses.length} silence cuts to the project.`);
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

  // Save (or update) the project's single captions edit: full-video span with
  // the chosen style and the loaded word transcript in its metadata, so the
  // render doesn't have to re-transcribe.
  const handleSaveCaptions = async () => {
    if (!projectId || !sourceDuration || transcriptWords.length === 0) return;

    setIsSavingCaptions(true);
    setCaptionsError(null);
    const metadata = {
      style: captionStyleName,
      words: transcriptWords.map(({ start, end, word }) => ({ start, end, word })),
    };
    if (captionWordsPerLine) {
      metadata.max_words_per_line = captionWordsPerLine;
    }

    try {
      const existing = savedCaptionsEdits[0];
      if (existing) {
        await updateProjectEdit(projectId, existing.id, { metadata });
      } else {
        await createProjectEdits(projectId, [
          {
            type: 'captions',
            source: 'captions_tool',
            start: 0,
            end: sourceDuration,
            enabled: true,
            media_asset_id: mediaAssetId,
            metadata,
          },
        ]);
      }
      const edits = await getProjectEdits(projectId);
      applyLoadedEdits(edits.edits);
      logActivity(`Saved ${captionStyleName} captions for the render.`);
    } catch (error) {
      console.error('Error saving captions:', error);
      setCaptionsError('Could not save captions.');
    } finally {
      setIsSavingCaptions(false);
    }
  };

  const handleToggleCaptionsEdit = async (edit) => {
    if (!projectId) return;

    setCaptionsError(null);
    try {
      const updated = await updateProjectEdit(projectId, edit.id, {
        enabled: edit.enabled === false,
      });
      setSavedCaptionsEdits((edits) =>
        edits.map((existing) => (existing.id === updated.id ? updated : existing))
      );
    } catch (error) {
      console.error('Error updating captions edit:', error);
      setCaptionsError('Could not update the saved captions.');
    }
  };

  const handleDeleteCaptionsEdit = async (edit) => {
    if (!projectId) return;

    setCaptionsError(null);
    try {
      await deleteProjectEdit(projectId, edit.id);
      setSavedCaptionsEdits((edits) =>
        edits.filter((existing) => existing.id !== edit.id)
      );
    } catch (error) {
      console.error('Error deleting captions edit:', error);
      setCaptionsError('Could not remove the saved captions.');
    }
  };

  // Default seconds a manual caption stays on screen from where it's placed.
  const DEFAULT_TEXT_CAPTION_DURATION = 4;

  // Create a manual streaming caption anchored at the current playhead time.
  const handleAddTextCaption = async (text, { position = 'bottom' } = {}) => {
    if (!projectId || sourceDuration === null) return;

    const trimmed = text?.trim();
    if (!trimmed) return;

    const length = Math.min(DEFAULT_TEXT_CAPTION_DURATION, sourceDuration);
    const start = Math.max(0, Math.min(currentTime, sourceDuration - length));

    setIsSavingTextCaption(true);
    setTextCaptionsError(null);
    try {
      await createProjectEdits(projectId, [
        {
          type: 'text_caption',
          source: 'notes_tool',
          start,
          end: start + length,
          enabled: true,
          media_asset_id: mediaAssetId,
          metadata: { text: trimmed, position },
        },
      ]);
      const edits = await getProjectEdits(projectId);
      applyLoadedEdits(edits.edits);
      logActivity(`Added a note at ${start.toFixed(1)}s.`);
    } catch (error) {
      console.error('Error adding note:', error);
      setTextCaptionsError('Could not add the note.');
    } finally {
      setIsSavingTextCaption(false);
    }
  };

  const handleUpdateTextCaption = async (caption, changes) => {
    if (!projectId) return;

    // Optimistic update so inline edits feel immediate.
    setSavedTextCaptions((captions) =>
      captions.map((existing) =>
        existing.id === caption.id ? { ...existing, ...changes } : existing
      )
    );
    setTextCaptionsError(null);
    try {
      const updated = await updateProjectEdit(projectId, caption.id, changes);
      setSavedTextCaptions((captions) =>
        captions.map((existing) =>
          existing.id === updated.id ? updated : existing
        )
      );
    } catch (error) {
      console.error('Error updating note:', error);
      setTextCaptionsError('Could not update the note.');
      try {
        const edits = await getProjectEdits(projectId);
        applyLoadedEdits(edits.edits);
      } catch (reloadError) {
        console.error('Error reloading edits:', reloadError);
      }
    }
  };

  const handleToggleTextCaption = (caption) =>
    handleUpdateTextCaption(caption, { enabled: caption.enabled === false });

  const handleDeleteTextCaption = async (caption) => {
    if (!projectId) return;

    setTextCaptionsError(null);
    try {
      await deleteProjectEdit(projectId, caption.id);
      setSavedTextCaptions((captions) =>
        captions.filter((existing) => existing.id !== caption.id)
      );
    } catch (error) {
      console.error('Error deleting note:', error);
      setTextCaptionsError('Could not remove the note.');
    }
  };

  const DEFAULT_OVERLAY_DURATION = 3;

  // Which state slice holds each overlay type, so timeline drag/trim/delete
  // can update the matching list without refetching everything.
  const overlaySettersByType = {
    zoom: setSavedZoomEdits,
    insert_stock_footage: setSavedStockEdits,
    diagram: setSavedDiagramEdits,
  };

  // Persist a new effect edit at the playhead with the given metadata, then
  // reload edits so the timeline lanes and the Edits list reflect it.
  const persistNewEdit = async (type, metadata, source = 'timeline') => {
    if (!projectId || !sourceDuration) return;

    const length = Math.min(DEFAULT_OVERLAY_DURATION, sourceDuration);
    const start = Math.max(0, Math.min(currentTime, sourceDuration - length));

    setToolError(null);
    try {
      await createProjectEdits(projectId, [
        {
          type,
          source,
          start,
          end: start + length,
          enabled: true,
          media_asset_id: mediaAssetId,
          metadata,
        },
      ]);
      const edits = await getProjectEdits(projectId);
      applyLoadedEdits(edits.edits);
      logActivity(`Added a ${type.replaceAll('_', ' ')} edit at ${start.toFixed(1)}s.`);
    } catch (error) {
      console.error('Error adding edit:', error);
      setToolError('Could not add the edit.');
    }
  };

  const handleAddOverlay = (type) => {
    let metadata = {};
    if (type === 'zoom') {
      metadata = { zoom_level: 1.2 };
    } else if (type === 'insert_stock_footage') {
      const query = window.prompt('Search Pexels for B-roll footage:');
      if (!query?.trim()) return undefined;
      metadata = { search_query: query.trim() };
    } else if (type === 'diagram') {
      metadata = { diagram_type: 'flowchart' };
    }
    return persistNewEdit(type, metadata);
  };

  // Manually add an effect edit from the Edits tab. Unlike the timeline's
  // add-overlay, stock starts with an empty query that is filled in (and
  // downloaded) inline from the Edits list afterward — no prompt.
  const handleAddEdit = (type) => {
    const metadata =
      type === 'zoom'
        ? { zoom_level: 1.2 }
        : type === 'insert_stock_footage'
          ? { search_query: '', media_type: 'video' }
          : { diagram_type: 'flowchart', title: 'Diagram' };
    return persistNewEdit(type, metadata, 'manual');
  };

  const handleUpdateOverlay = async (overlay, changes) => {
    if (!projectId) return;

    const setEdits = overlaySettersByType[overlay.type];
    // Optimistic update so the clip doesn't snap back while the save runs.
    setEdits?.((edits) =>
      edits.map((edit) =>
        edit.id === overlay.id ? { ...edit, ...changes } : edit
      )
    );
    setToolError(null);
    try {
      const updated = await updateProjectEdit(projectId, overlay.id, changes);
      setEdits?.((edits) =>
        edits.map((edit) => (edit.id === updated.id ? updated : edit))
      );
    } catch (error) {
      console.error('Error updating overlay:', error);
      setToolError('Could not save the overlay change.');
      try {
        const edits = await getProjectEdits(projectId);
        applyLoadedEdits(edits.edits);
      } catch (reloadError) {
        console.error('Error reloading edits:', reloadError);
      }
    }
  };

  const handleDeleteOverlay = async (overlay) => {
    if (!projectId) return;

    setToolError(null);
    try {
      await deleteProjectEdit(projectId, overlay.id);
      overlaySettersByType[overlay.type]?.((edits) =>
        edits.filter((edit) => edit.id !== overlay.id)
      );
    } catch (error) {
      console.error('Error deleting overlay:', error);
      setToolError('Could not delete the overlay.');
    }
  };

  // Fetch (or re-fetch) a Pexels clip for one saved stock-footage overlay and
  // persist the new file on the edit, so render uses the replacement clip.
  const handleRefetchStockFootage = async (overlay, query) => {
    const trimmed = query?.trim();
    if (!trimmed) return;

    setStockRefetch((current) => ({
      ...current,
      [overlay.id]: { status: 'loading' },
    }));
    try {
      const mediaType =
        overlay.metadata?.media_type === 'image' ? 'image' : 'video';
      const result = await downloadStockFootage(trimmed, 'hd', mediaType);
      await handleUpdateOverlay(overlay, {
        metadata: {
          ...overlay.metadata,
          search_query: trimmed,
          footage_path: result.file_path,
          media_type: result.media_type || mediaType,
        },
      });
      setStockRefetch((current) => ({
        ...current,
        [overlay.id]: { status: 'done' },
      }));
    } catch (error) {
      console.error('Error re-downloading stock footage:', error);
      setStockRefetch((current) => ({
        ...current,
        [overlay.id]: {
          status: 'error',
          error: error.response?.data?.detail || 'Download failed.',
        },
      }));
    }
  };

  const handleSuggestDiagrams = async () => {
    if (!fileId) return;

    setIsSuggestingDiagrams(true);
    setDiagramError(null);
    try {
      const result = await suggestDiagrams(fileId, 'base');
      // Match the overlay orientation to the source by default; each card has
      // a toggle to override it.
      const defaultLayout =
        videoAspectRatio && videoAspectRatio < 1 ? 'portrait' : 'landscape';
      setDiagramSuggestions(
        (result.diagrams || [])
          .map((diagram) => ({
            id: crypto.randomUUID(),
            ...diagram,
            layout: defaultLayout,
          }))
          .sort((a, b) => a.start - b.start)
      );
      logActivity(
        `Diagram analysis suggested ${(result.diagrams || []).length} overlays.`
      );
    } catch (error) {
      console.error('Error suggesting diagrams:', error);
      const detail = error.response?.data?.detail;
      setDiagramError(
        detail
          ? `Could not suggest diagrams: ${detail}`
          : 'Could not suggest diagrams for this video.'
      );
    } finally {
      setIsSuggestingDiagrams(false);
    }
  };

  // Accept one diagram suggestion: persist it as a `diagram` edit so it shows
  // up on the timeline's Diagram lane, then drop it from the suggestion list.
  const handleAcceptDiagram = async (suggestion) => {
    if (!projectId) return;

    setSavingDiagramId(suggestion.id);
    setDiagramError(null);
    try {
      await createProjectEdits(projectId, [
        {
          type: 'diagram',
          source: 'diagram_suggestion',
          start: Number(suggestion.start) || 0,
          end: Number(suggestion.end) || 0,
          enabled: true,
          media_asset_id: mediaAssetId,
          metadata: {
            diagram_type: suggestion.diagram_type,
            title: suggestion.title,
            transcript_excerpt: suggestion.transcript_excerpt,
            reason: suggestion.reason,
            graph: suggestion.graph,
            layout: suggestion.layout || 'landscape',
          },
        },
      ]);
      const edits = await getProjectEdits(projectId);
      applyLoadedEdits(edits.edits);
      setDiagramSuggestions((items) =>
        items.filter((item) => item.id !== suggestion.id)
      );
      logActivity(
        `Added diagram "${suggestion.title || suggestion.diagram_type}" to the timeline.`
      );
    } catch (error) {
      console.error('Error saving diagram edit:', error);
      setDiagramError('Could not add the diagram to the timeline.');
    } finally {
      setSavingDiagramId(null);
    }
  };

  // Switch a suggestion between landscape and portrait. Any rendered preview
  // is dropped because it no longer matches the chosen orientation.
  const handleSetDiagramLayout = (suggestionId, layout) => {
    setDiagramSuggestions((items) =>
      items.map((item) =>
        item.id === suggestionId ? { ...item, layout } : item
      )
    );
    setDiagramPreviews((previews) => {
      if (!(suggestionId in previews)) return previews;
      const next = { ...previews };
      delete next[suggestionId];
      return next;
    });
  };

  const handleDismissDiagram = (suggestionId) => {
    setDiagramSuggestions((items) =>
      items.filter((item) => item.id !== suggestionId)
    );
    setDiagramPreviews((previews) => {
      if (!(suggestionId in previews)) return previews;
      const next = { ...previews };
      delete next[suggestionId];
      return next;
    });
  };

  // Render one suggestion's motion diagram with Manim and show it in the
  // card's preview player. The server caches by spec, so re-renders are fast.
  const handleRenderDiagramPreview = async (suggestion) => {
    setDiagramPreviews((previews) => ({
      ...previews,
      [suggestion.id]: { status: 'rendering' },
    }));
    try {
      const result = await renderDiagramPreview(suggestion);
      setDiagramPreviews((previews) => ({
        ...previews,
        [suggestion.id]: {
          status: 'done',
          url: getAbsoluteAPIURL(result.video_url),
        },
      }));
      logActivity(
        `Rendered diagram preview "${suggestion.title || suggestion.diagram_type}".`
      );
    } catch (error) {
      console.error('Error rendering diagram preview:', error);
      const detail = error.response?.data?.detail;
      setDiagramPreviews((previews) => ({
        ...previews,
        [suggestion.id]: {
          status: 'error',
          error: detail || 'Could not render the diagram preview.',
        },
      }));
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
      logActivity(`AI editing plan generated with ${items.length} suggestions.`);
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
      logActivity(`Saved ${zoomItems.length} zoom edits from the plan.`);
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

      const mediaType =
        item.parameters?.media_type === 'image' ? 'image' : 'video';
      try {
        const result = await downloadStockFootage(query, 'hd', mediaType);
        const filename = result.file_path.split('/').pop();
        setStockDownloads((current) => ({
          ...current,
          [item.id]: {
            status: 'done',
            filename,
            filePath: result.file_path,
            previewUrl: getStockFootageURL(filename),
            searchQuery: query,
            mediaType: result.media_type || mediaType,
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
              media_type: download.mediaType || 'video',
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
      logActivity(`Saved ${ready.length} stock footage clips to the project.`);
    } catch (error) {
      console.error('Error saving stock footage edits:', error);
      setStockError('Could not save stock footage edits to the project.');
    }
  };

  // Send a user question to the project assistant. The conversation turns go
  // as history; log entries and the transcript ride along as context.
  const handleSendChatMessage = async (text) => {
    if (!projectId || isChatSending) return;

    const userMessage = {
      id: crypto.randomUUID(),
      role: 'user',
      content: text,
    };
    const history = [...chatMessages, userMessage]
      .filter((message) => message.role === 'user' || message.role === 'assistant')
      .map(({ role, content }) => ({ role, content }));
    const activityLog = chatMessages
      .filter((message) => message.role === 'log')
      .map((message) => `${message.time} ${message.content}`);

    setChatMessages((messages) => [...messages, userMessage]);
    setIsChatSending(true);
    setChatError(null);
    try {
      const result = await sendProjectChat(projectId, history, {
        transcript: transcriptWords.map((word) => word.word).join(' '),
        activityLog,
      });
      // Surface each tool call the agent made as an activity log line, then
      // the reply itself.
      (result.actions || []).forEach((action) => {
        logActivity(`Assistant: ${action.summary}`);
      });
      setChatMessages((messages) => [
        ...messages,
        { id: crypto.randomUUID(), role: 'assistant', content: result.reply },
      ]);
      // The agent edited the project: reload edits so markers, counts, and
      // overlay lanes reflect what it did.
      if (result.edits_changed) {
        const edits = await getProjectEdits(projectId);
        applyLoadedEdits(edits.edits);
      }
    } catch (error) {
      console.error('Error sending chat message:', error);
      const detail = error.response?.data?.detail;
      setChatError(
        detail ? `Assistant error: ${detail}` : 'Could not reach the assistant.'
      );
    } finally {
      setIsChatSending(false);
    }
  };

  // Rendering runs as a background job on the backend: start it, then poll its
  // status for progress and the final download URL. The interval id lives in
  // renderPollRef so it can be cleared on completion, error, or unmount.
  const stopRenderPolling = () => {
    if (renderPollRef.current) {
      clearInterval(renderPollRef.current);
      renderPollRef.current = null;
    }
  };

  const handleRenderProject = async () => {
    if (!projectId) return;

    stopRenderPolling();
    setIsRendering(true);
    setRenderProgress(0);
    setRenderResult(null);
    setToolError(null);

    try {
      const { job_id: jobId } = await renderProject(projectId);
      renderPollRef.current = setInterval(async () => {
        try {
          const status = await getRenderStatus(jobId);
          setRenderProgress(status.progress || 0);
          if (status.status === 'done') {
            stopRenderPolling();
            setRenderProgress(1);
            setRenderResult({
              filename: status.filename,
              url: getAbsoluteAPIURL(status.output_url),
              appliedEdits: status.applied_edits,
            });
            setIsRendering(false);
            logActivity(
              `Rendered "${status.filename}" with ${status.applied_edits} edits applied.`
            );
          } else if (status.status === 'error') {
            stopRenderPolling();
            setToolError(status.error || 'Could not render the project.');
            setIsRendering(false);
            logActivity('Render failed. Check the render page for details.');
          }
        } catch (error) {
          stopRenderPolling();
          console.error('Error polling render status:', error);
          setToolError('Lost contact with the render job.');
          setIsRendering(false);
        }
      }, RENDER_POLL_INTERVAL_MS);
    } catch (error) {
      console.error('Error starting render:', error);
      setToolError('Could not start the render.');
      setIsRendering(false);
      logActivity('Render failed. Check the render page for details.');
    }
  };

  // Stop any in-flight render polling if the app unmounts.
  useEffect(() => stopRenderPolling, []);

  // --- Dota 2 death detection ---------------------------------------------
  const stopDeathPolling = () => {
    if (deathPollRef.current) {
      clearInterval(deathPollRef.current);
      deathPollRef.current = null;
    }
  };
  useEffect(() => stopDeathPolling, []);

  const stopMarkerPolling = () => {
    if (markerPollRef.current) {
      clearInterval(markerPollRef.current);
      markerPollRef.current = null;
    }
  };
  useEffect(() => stopMarkerPolling, []);

  // Detect kills, deaths and assists in one scan and place their markers on the
  // play bar (K/A from HUD OCR, D from the respawn-box signal). Reuses the
  // death-detection endpoint with the K/D/A OCR pass enabled.
  const handleDetectMarkers = async () => {
    if (!fileId) return;

    stopMarkerPolling();
    setMarkerStatus('detecting');
    setMarkerError(null);
    setGamingEvents([]);
    try {
      const { job_id: jobId } = await startDeathDetection(fileId, {
        team: deathTeam,
        playerSlot: deathSelectedSlot,
        detectKda: true,
      });
      markerPollRef.current = setInterval(async () => {
        try {
          const status = await getDeathDetectionStatus(jobId);
          if (status.status === 'done') {
            stopMarkerPolling();
            setGamingEvents(status.events || []);
            setMarkerStatus('done');
            logActivity(
              `Placed ${(status.events || []).length} K/D/A markers on the play bar.`
            );
          } else if (status.status === 'error') {
            stopMarkerPolling();
            setMarkerError(status.error || 'Marker detection failed.');
            setMarkerStatus('error');
          }
        } catch (error) {
          stopMarkerPolling();
          console.error('Error polling marker detection:', error);
          setMarkerError('Lost contact with the detection job.');
          setMarkerStatus('error');
        }
      }, DEATH_POLL_INTERVAL_MS);
    } catch (error) {
      console.error('Error starting marker detection:', error);
      setMarkerError('Could not start marker detection.');
      setMarkerStatus('error');
    }
  };

  // Load the 5 team-portrait thumbnails so the user can correct the auto slot.
  const handleLoadDeathSlots = async () => {
    if (!fileId) return;
    setDeathStatus('loading-slots');
    setDeathError(null);
    try {
      const data = await getSlotPreview(fileId, deathTeam);
      setDeathSlots(data.slots || []);
      if (deathPlayerSlot === null && data.auto_slot >= 0) {
        setDeathPlayerSlot(data.auto_slot);
        setDeathConfidence(data.confidence);
      }
      setDeathStatus('idle');
    } catch (error) {
      console.error('Error loading slot preview:', error);
      const detail = error.response?.data?.detail;
      setDeathError(detail || 'Could not load hero portraits.');
      setDeathStatus('error');
    }
  };

  const handleSelectDeathSlot = (index) => {
    setDeathSelectedSlot(index);
  };

  // Start detection (auto slot, or the manual override) and poll to completion.
  const handleDetectDeaths = async () => {
    if (!fileId) return;

    stopDeathPolling();
    setDeathStatus('detecting');
    setDeathError(null);
    setDeathIntervals([]);
    try {
      const { job_id: jobId } = await startDeathDetection(fileId, {
        team: deathTeam,
        playerSlot: deathSelectedSlot,
      });
      deathPollRef.current = setInterval(async () => {
        try {
          const status = await getDeathDetectionStatus(jobId);
          if (status.status === 'done') {
            stopDeathPolling();
            setDeathIntervals(status.intervals || []);
            if (status.player_slot != null) setDeathPlayerSlot(status.player_slot);
            if (status.confidence != null) setDeathConfidence(status.confidence);
            setDeathStatus('done');
            logActivity(
              `Death detection found ${(status.intervals || []).length} deaths.`
            );
          } else if (status.status === 'error') {
            stopDeathPolling();
            setDeathError(status.error || 'Death detection failed.');
            setDeathStatus('error');
          }
        } catch (error) {
          stopDeathPolling();
          console.error('Error polling death detection:', error);
          setDeathError('Lost contact with the detection job.');
          setDeathStatus('error');
        }
      }, DEATH_POLL_INTERVAL_MS);
    } catch (error) {
      console.error('Error starting death detection:', error);
      setDeathError('Could not start death detection.');
      setDeathStatus('error');
    }
  };

  // Persist the detected dead intervals as cut edits on the project.
  const handleAddDeathCuts = async () => {
    if (!projectId || deathIntervals.length === 0) return;

    try {
      await createProjectEdits(
        projectId,
        deathIntervals.map((iv) => ({
          type: 'cut',
          source: 'death_detection',
          start: iv.start,
          end: iv.end,
          enabled: true,
          media_asset_id: mediaAssetId,
          metadata: { duration: iv.duration, kind: 'death' },
        }))
      );
      const edits = await getProjectEdits(projectId);
      applyLoadedEdits(edits.edits);
      setDeathCutsSaved(deathIntervals.length);
      logActivity(`Added ${deathIntervals.length} death cuts to the project.`);
    } catch (error) {
      console.error('Error saving death cuts:', error);
      setDeathError('Could not add death cuts to the project.');
    }
  };

  // Copy the current playhead time into the highlight start/end field.
  const handleSetHighlightToPlayhead = (which) => {
    const value = String(Number(currentTime.toFixed(2)));
    if (which === 'start') setHighlightStart(value);
    else setHighlightEnd(value);
  };

  // Trim a quick clip between the start/end fields into a downloadable file.
  const handleCreateHighlight = async () => {
    if (!fileId) return;
    const start = parseFloat(highlightStart);
    const end = parseFloat(highlightEnd);
    if (Number.isNaN(start) || Number.isNaN(end) || end <= start) {
      setHighlightError('Enter a valid start and end (end must be after start).');
      setHighlightStatus('error');
      return;
    }
    setHighlightStatus('creating');
    setHighlightError(null);
    setHighlightResult(null);
    try {
      const clip = await createHighlightClip(fileId, start, end);
      setHighlightResult(clip);
      setHighlightStatus('done');
      logActivity(`Created a ${clip.duration.toFixed(1)}s highlight clip.`);
    } catch (error) {
      console.error('Error creating highlight clip:', error);
      setHighlightError(
        error?.response?.data?.detail || 'Could not create the highlight clip.'
      );
      setHighlightStatus('error');
    }
  };

  const handleGoToRender = () => {
    setCurrentView('render');
  };

  const handleBackToEditor = () => {
    setCurrentView('editor');
  };

  const resetProjectState = () => {
    // Stop tracking the outgoing project's render before tearing its state down.
    stopRenderPolling();
    setIsRendering(false);
    setRenderProgress(0);
    if (videoSrc?.startsWith('blob:')) {
      URL.revokeObjectURL(videoSrc);
    }
    setVideoSrc(null);
    setSelectedFile(null);
    setFileId(null);
    setProjectId(null);
    setMediaAssetId(null);
    setWaveformData(null);
    setSourceDuration(null);
    setTimelineSegments([]);
    setTimelineDirty(false);
    setHasSavedTimeline(false);
    activeSegmentIndexRef.current = 0;
    setTranscriptWords([]);
    setDetectedPauses([]);
    setEditOperations([]);
    setSavedZoomEdits([]);
    setSavedStockEdits([]);
    setSavedDiagramEdits([]);
    setSavedCaptionsEdits([]);
    setCaptionsError(null);
    setSavedTextCaptions([]);
    setTextCaptionsError(null);
    setEditingPlan([]);
    setDiagramSuggestions([]);
    setDiagramError(null);
    setSavingDiagramId(null);
    setVideoAspectRatio(null);
    setInspected(null);
    setStockRefetch({});
    setStockDownloads({});
    setStockError(null);
    setPlanError(null);
    setToolError(null);
    setRenderResult(null);
    setChatMessages([]);
    setChatError(null);
    setDeathStatus('idle');
    setDeathError(null);
    setDeathIntervals([]);
    setDeathPlayerSlot(null);
    setDeathConfidence(null);
    setDeathSlots([]);
    setDeathSelectedSlot(null);
    setDeathCutsSaved(0);
    stopMarkerPolling();
    setGamingEvents([]);
    setMarkerStatus('idle');
    setMarkerError(null);
    setHighlightStart('');
    setHighlightEnd('');
    setHighlightStatus('idle');
    setHighlightError(null);
    setHighlightResult(null);
    setIsGaming(false);
    setActivePanel('tools');
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
                  onClick={() => {
                    setIsGaming(false);
                    setSourceMode('upload');
                  }}
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
                  onClick={() => {
                    setIsGaming(false);
                    setSourceMode('record');
                  }}
                >
                  <svg width="40" height="40" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M17 10.5V7a1 1 0 0 0-1-1H4a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-3.5l4 4v-11l-4 4z" />
                  </svg>
                  <strong>Record new footage</strong>
                  <span>Capture video with your camera and microphone</span>
                </button>
                <button
                  type="button"
                  className="source-card"
                  onClick={() => {
                    setIsGaming(false);
                    setSourceMode('youtube');
                  }}
                >
                  <svg width="40" height="40" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M21.6 7.2a2.6 2.6 0 0 0-1.83-1.84C18.15 4.92 12 4.92 12 4.92s-6.15 0-7.77.44A2.6 2.6 0 0 0 2.4 7.2C1.97 8.82 1.97 12 1.97 12s0 3.18.43 4.8a2.6 2.6 0 0 0 1.83 1.84c1.62.44 7.77.44 7.77.44s6.15 0 7.77-.44a2.6 2.6 0 0 0 1.83-1.84c.43-1.62.43-4.8.43-4.8s0-3.18-.43-4.8zM10 15.5v-7l6 3.5-6 3.5z" />
                  </svg>
                  <strong>Edit an existing YouTube video</strong>
                  <span>Paste a YouTube link to download and edit it</span>
                </button>
                <button
                  type="button"
                  className="source-card"
                  onClick={() => {
                    setIsGaming(true);
                    setSourceMode('gaming');
                  }}
                >
                  <svg width="40" height="40" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M17 4H7a6 6 0 0 0-6 6v4a3 3 0 0 0 5.4 1.8L8 14h8l1.6 1.8A3 3 0 0 0 23 14v-4a6 6 0 0 0-6-6zM8 12H6v2H5v-2H3v-1h2V9h1v2h2v1zm7-2a1 1 0 1 1 0-2 1 1 0 0 1 0 2zm3 2a1 1 0 1 1 0-2 1 1 0 0 1 0 2z" />
                  </svg>
                  <strong>Edit a gaming video</strong>
                  <span>Upload a Dota 2 recording and auto-cut death time</span>
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
              ) : sourceMode === 'youtube' ? (
                <VideoUpload
                  youtubeOnly
                  onYouTubeImport={handleYouTubeImport}
                />
              ) : sourceMode === 'gaming' ? (
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
              pointMarkers={isGaming ? gamingEvents : []}
              onAspectRatioChange={setVideoAspectRatio}
              captionPreview={captionPreview}
              textCaptions={savedTextCaptions}
            />

            <Timeline
              segments={timelineSegments}
              duration={sourceDuration || 0}
              waveformData={waveformData}
              currentTime={currentTime}
              isDirty={timelineDirty}
              isSaving={isSavingTimeline}
              overlays={timelineOverlays}
              selectedSegmentId={
                inspectorSelection?.kind === 'segment' ? inspected.id : null
              }
              selectedOverlayId={
                inspectorSelection?.kind === 'overlay' ? inspected.id : null
              }
              onSeek={handleSeek}
              onSplitAtPlayhead={handleSplitAtPlayhead}
              onReorder={handleReorderSegments}
              onDeleteSegment={handleDeleteSegment}
              onReset={handleResetTimeline}
              onSave={handleSaveTimeline}
              onAddOverlay={handleAddOverlay}
              onUpdateOverlay={handleUpdateOverlay}
              onDeleteOverlay={handleDeleteOverlay}
              onSelectSegment={handleSelectSegment}
              onSelectOverlay={handleSelectOverlay}
            />

            <InspectorPanel
              selection={inspectorSelection}
              segmentCount={timelineSegments.length}
              sourceDuration={sourceDuration || 0}
              stockStatus={
                inspectorSelection?.kind === 'overlay'
                  ? stockRefetch[inspectorSelection.overlay.id]
                  : null
              }
              onClose={() => setInspected(null)}
              onSeek={handleSeek}
              onUpdateSegment={handleUpdateSegment}
              onDeleteSegment={handleDeleteSegment}
              onUpdateOverlay={handleUpdateOverlay}
              onDeleteOverlay={handleDeleteOverlay}
              onRefetchStock={handleRefetchStockFootage}
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
            <div className="panel-top">
              <div className="panel-tabs">
              <button
                type="button"
                className={activePanel === 'tools' ? 'active' : ''}
                onClick={() => setActivePanel('tools')}
              >
                Tools
              </button>
              {isGaming && (
                <button
                  type="button"
                  className={activePanel === 'deaths' ? 'active' : ''}
                  onClick={() => setActivePanel('deaths')}
                >
                  Deaths
                </button>
              )}
              {isGaming && (
                <button
                  type="button"
                  className={activePanel === 'highlights' ? 'active' : ''}
                  onClick={() => setActivePanel('highlights')}
                >
                  Highlights
                </button>
              )}
              <button
                type="button"
                className={activePanel === 'plan' ? 'active' : ''}
                onClick={() => setActivePanel('plan')}
              >
                Plan
              </button>
              <button
                type="button"
                className={activePanel === 'edits' ? 'active' : ''}
                onClick={() => setActivePanel('edits')}
              >
                Edits
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
                className={activePanel === 'diagrams' ? 'active' : ''}
                onClick={() => setActivePanel('diagrams')}
              >
                Diagrams
              </button>
              <button
                type="button"
                className={activePanel === 'captions' ? 'active' : ''}
                onClick={() => setActivePanel('captions')}
              >
                Captions
              </button>
              <button
                type="button"
                className={activePanel === 'notes' ? 'active' : ''}
                onClick={() => setActivePanel('notes')}
              >
                Notes
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
                  loading={{
                    detecting: isDetectingSilence,
                    confirming: isConfirmingCuts,
                  }}
                  error={toolError}
                  onDetect={handleDetectSilence}
                  onToggleProposal={handleToggleProposedPause}
                  onConfirm={handleConfirmSilenceCuts}
                  onToggleEdit={handleToggleStoredEdit}
                  onDeleteEdit={handleDeleteStoredEdit}
                  onSeek={handleSeek}
                />
              )}
              {activePanel === 'tools' && (
                <CaptionTool key={fileId} fileId={fileId} useGpu={settings.useGpu} />
              )}
              {activePanel === 'deaths' && (
                <DeathCutsPanel
                  hasProject={Boolean(projectId)}
                  team={deathTeam}
                  onChangeTeam={setDeathTeam}
                  status={deathStatus}
                  error={deathError}
                  intervals={deathIntervals}
                  playerSlot={deathPlayerSlot}
                  confidence={deathConfidence}
                  slots={deathSlots}
                  selectedSlot={deathSelectedSlot}
                  onLoadSlots={handleLoadDeathSlots}
                  onSelectSlot={handleSelectDeathSlot}
                  onDetect={handleDetectDeaths}
                  onSeek={handleSeek}
                  onAddCuts={handleAddDeathCuts}
                  savedCount={deathCutsSaved}
                />
              )}
              {activePanel === 'highlights' && (
                <HighlightsPanel
                  hasVideo={Boolean(fileId)}
                  currentTime={currentTime}
                  start={highlightStart}
                  end={highlightEnd}
                  status={highlightStatus}
                  error={highlightError}
                  result={highlightResult}
                  markerStatus={markerStatus}
                  markerError={markerError}
                  markerCount={gamingEvents.length}
                  team={deathTeam}
                  slots={deathSlots}
                  selectedSlot={deathSelectedSlot}
                  playerSlot={deathPlayerSlot}
                  confidence={deathConfidence}
                  slotsLoading={deathStatus === 'loading-slots'}
                  slotError={deathStatus === 'error' ? deathError : null}
                  onChangeTeam={setDeathTeam}
                  onLoadSlots={handleLoadDeathSlots}
                  onSelectSlot={handleSelectDeathSlot}
                  onDetectMarkers={handleDetectMarkers}
                  onChangeStart={setHighlightStart}
                  onChangeEnd={setHighlightEnd}
                  onSetToPlayhead={handleSetHighlightToPlayhead}
                  onCreate={handleCreateHighlight}
                />
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
              {activePanel === 'edits' && (
                <EditsPanel
                  edits={timelineOverlays}
                  sourceDuration={sourceDuration || 0}
                  stockRefetch={stockRefetch}
                  error={toolError}
                  hasProject={Boolean(projectId)}
                  onAddEdit={handleAddEdit}
                  onUpdateOverlay={handleUpdateOverlay}
                  onDeleteOverlay={handleDeleteOverlay}
                  onRefetchStock={handleRefetchStockFootage}
                  onSeek={handleSeek}
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
              {activePanel === 'diagrams' && (
                <DiagramPanel
                  suggestions={diagramSuggestions}
                  loading={isSuggestingDiagrams}
                  savingId={savingDiagramId}
                  error={diagramError}
                  hasVideo={Boolean(fileId)}
                  savedCount={savedDiagramEdits.length}
                  previews={diagramPreviews}
                  onSuggest={handleSuggestDiagrams}
                  onAccept={handleAcceptDiagram}
                  onDismiss={handleDismissDiagram}
                  onRenderPreview={handleRenderDiagramPreview}
                  onSetLayout={handleSetDiagramLayout}
                  onSeek={handleSeek}
                />
              )}
              {activePanel === 'captions' && (
                <CaptionsPanel
                  captionStyles={captionStyles}
                  selectedStyle={captionStyleName}
                  wordsPerLine={captionWordsPerLine}
                  savedCaptions={savedCaptionsEdits}
                  hasWords={transcriptWords.length > 0}
                  saving={isSavingCaptions}
                  error={captionsError}
                  onSelectStyle={setCaptionStyleName}
                  onChangeWordsPerLine={setCaptionWordsPerLine}
                  onSave={handleSaveCaptions}
                  onToggle={handleToggleCaptionsEdit}
                  onDelete={handleDeleteCaptionsEdit}
                />
              )}
              {activePanel === 'notes' && (
                <TextCaptionsPanel
                  captions={savedTextCaptions}
                  currentTime={currentTime}
                  hasProject={Boolean(projectId)}
                  saving={isSavingTextCaption}
                  error={textCaptionsError}
                  onAdd={handleAddTextCaption}
                  onUpdate={handleUpdateTextCaption}
                  onToggle={handleToggleTextCaption}
                  onDelete={handleDeleteTextCaption}
                  onSeek={handleSeek}
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
            </div>

            <ChatPanel
              messages={chatMessages}
              isSending={isChatSending}
              error={chatError}
              hasProject={Boolean(projectId)}
              onSend={handleSendChatMessage}
            />
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
          {savedDiagramEdits.length > 0 && (
            <span>{savedDiagramEdits.length} diagram overlays</span>
          )}
          {savedTextCaptions.filter((edit) => edit.enabled !== false).length > 0 && (
            <span>
              {savedTextCaptions.filter((edit) => edit.enabled !== false).length}{' '}
              notes
            </span>
          )}
          {hasSavedTimeline && (
            <span>custom timeline ({timelineSegments.length} segments)</span>
          )}
          <span>{selectedFile?.name || 'No video selected'}</span>
        </div>

        <button
          type="button"
          className="render-submit"
          onClick={handleRenderProject}
          disabled={isRendering || !projectId || !hasRenderableContent}
        >
          {isRendering ? 'Rendering...' : 'Render Video'}
        </button>

        {isRendering && (
          <div
            className="render-progress"
            role="progressbar"
            aria-valuenow={Math.round(renderProgress * 100)}
            aria-valuemin={0}
            aria-valuemax={100}
          >
            <div className="render-progress-track">
              <div
                className="render-progress-fill"
                style={{ width: `${Math.round(renderProgress * 100)}%` }}
              />
            </div>
            <span className="render-progress-label">
              Rendering… {Math.round(renderProgress * 100)}%
            </span>
          </div>
        )}

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
        <div className="top-bar-actions">
          {projectId && currentView === 'editor' && (
            <button
              type="button"
              className="render-cta"
              onClick={handleGoToRender}
              disabled={!hasRenderableContent}
              title={
                hasRenderableContent
                  ? 'Choose export settings and render the video'
                  : 'Add an edit, overlay, or timeline change first'
              }
            >
              Final Render
            </button>
          )}
          <button
            type="button"
            className="settings-button"
            onClick={() => setSettingsOpen(true)}
            aria-label="Open settings"
          >
            ⚙ Settings
          </button>
        </div>
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
