import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  cancelRankingJob,
  fetchRankingOverlay,
  getAbsoluteAPIURL,
  getRankingJob,
  getRankingProject,
  saveRankingProject,
  startRankingDownload,
  startRankingRender,
  uploadRankingClip,
} from '../../services/api';
import {
  CANVAS_HEIGHT,
  CANVAS_WIDTH,
  FPS,
  applyAccent,
  buildSchedule,
  editRunsText,
  framingBox,
  resolvedOut,
  runsText,
  segmentIndexAtFrame,
  viewportFor,
} from '../../utils/rankingTimeline';
import styles from './RankingShorts.module.css';

const AUTOSAVE_MS = 600;
const POLL_MS = 1000;
const FONTS = ['montserrat', 'anton', 'bangers'];
const ACTIVE = ['queued', 'running'];

function errorText(err, fallback) {
  const detail = err?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (detail?.message) return detail.message;
  return err?.message || fallback;
}

/** Copy server-owned clip fields into the local draft without losing local edits. */
function mergeServerClips(local, server) {
  const byId = new Map(server.clips.map((c) => [c.id, c]));
  return {
    ...local,
    clips: local.clips.map((clip) => {
      const remote = byId.get(clip.id);
      if (!remote) return clip;
      const merged = {
        ...clip,
        asset_id: remote.asset_id,
        media: remote.media,
        source_generation: remote.source_generation,
      };
      if (remote.source_generation !== clip.source_generation) {
        Object.assign(merged, {
          trim_in: remote.trim_in,
          trim_out: remote.trim_out,
          fit: remote.fit,
          focal_x: remote.focal_x,
          focal_y: remote.focal_y,
          zoom: remote.zoom,
          provider: remote.provider,
          name: clip.name.trim() ? clip.name : remote.name,
        });
      }
      return merged;
    }),
  };
}

function Field({ label, children }) {
  return (
    <label className={styles.field}>
      <span>{label}</span>
      {children}
    </label>
  );
}

export default function RankingShorts({ projectId, onExit }) {
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState('');
  const [doc, setDoc] = useState(null);
  const [media, setMedia] = useState({});
  const [issues, setIssues] = useState([]);
  const [jobs, setJobs] = useState([]);
  const [projectName, setProjectName] = useState('');
  const [saveState, setSaveState] = useState('saved');
  const [saveMessage, setSaveMessage] = useState('');
  const [selectedId, setSelectedId] = useState(null);
  const [urls, setUrls] = useState({});
  const [dragId, setDragId] = useState(null);
  const [tab, setTab] = useState('clips');
  const [guides, setGuides] = useState(false);
  const [overlayUrl, setOverlayUrl] = useState('');
  const [frame, setFrame] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [exportJob, setExportJob] = useState(null);
  const [exportError, setExportError] = useState('');
  const [notice, setNotice] = useState('');

  const revisionRef = useRef(1);
  const editVersion = useRef(0);
  const savedVersion = useRef(0);
  const savingRef = useRef(false);
  const docRef = useRef(null);
  const nameRef = useRef('');
  const videoRef = useRef(null);
  const frameRef = useRef(0);
  const lastTickRef = useRef(0);
  const pendingSeek = useRef(null);
  const knownDone = useRef(new Set());
  const headingInput = useRef(null);

  docRef.current = doc;
  nameRef.current = projectName;

  const applyPayload = useCallback((payload, { replaceDoc }) => {
    revisionRef.current = payload.revision;
    setMedia(payload.media || {});
    setIssues(payload.issues || []);
    setJobs(payload.jobs || []);
    setProjectName((current) => (replaceDoc || !current ? payload.project.name : current));
    if (replaceDoc) {
      setDoc(payload.document);
    } else {
      setDoc((current) => (current ? mergeServerClips(current, payload.document) : payload.document));
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    getRankingProject(projectId)
      .then((payload) => {
        if (cancelled) return;
        applyPayload(payload, { replaceDoc: true });
        setSelectedId(payload.document.clips[0]?.id ?? null);
        setLoaded(true);
      })
      .catch((err) => !cancelled && setLoadError(errorText(err, 'Could not open project')));
    return () => {
      cancelled = true;
    };
  }, [projectId, applyPayload]);

  const refresh = useCallback(async () => {
    const payload = await getRankingProject(projectId);
    applyPayload(payload, { replaceDoc: false });
    return payload;
  }, [projectId, applyPayload]);

  const edit = useCallback((updater) => {
    setDoc((current) => (current ? updater(current) : current));
    editVersion.current += 1;
    setSaveState('saving');
  }, []);

  const updateClip = (id, patch) =>
    edit((d) => ({ ...d, clips: d.clips.map((c) => (c.id === id ? { ...c, ...patch } : c)) }));
  const updateHeading = (patch) => edit((d) => ({ ...d, heading: { ...d.heading, ...patch } }));
  const updateRanking = (patch) => edit((d) => ({ ...d, ranking: { ...d.ranking, ...patch } }));
  const updateCanvas = (patch) => edit((d) => ({ ...d, canvas: { ...d.canvas, ...patch } }));

  // ---- autosave ----
  const saveNow = useCallback(async () => {
    if (savingRef.current || !docRef.current) return;
    const version = editVersion.current;
    if (version === savedVersion.current) return;
    savingRef.current = true;
    setSaveState('saving');
    try {
      const payload = await saveRankingProject(
        projectId,
        revisionRef.current,
        docRef.current,
        nameRef.current
      );
      savedVersion.current = version;
      revisionRef.current = payload.revision;
      setIssues(payload.issues || []);
      setMedia(payload.media || {});
      setJobs(payload.jobs || []);
      setSaveState(editVersion.current === version ? 'saved' : 'saving');
      setSaveMessage('');
    } catch (err) {
      const status = err?.response?.status;
      if (status === 409) {
        setSaveState('conflict');
      } else if (status === 422) {
        setSaveState('invalid');
        setSaveMessage(errorText(err, 'Invalid composition'));
        savedVersion.current = version; // do not retry the same invalid draft
      } else {
        setSaveState('error');
        setSaveMessage(errorText(err, 'Save failed'));
      }
    } finally {
      savingRef.current = false;
    }
  }, [projectId]);

  useEffect(() => {
    if (!loaded || editVersion.current === savedVersion.current) return undefined;
    if (saveState === 'conflict' || saveState === 'error') return undefined;
    const timer = setTimeout(saveNow, AUTOSAVE_MS);
    return () => clearTimeout(timer);
  }, [doc, projectName, loaded, saveNow, saveState]);

  useEffect(() => {
    const onUnload = (event) => {
      if (editVersion.current !== savedVersion.current) event.preventDefault();
    };
    window.addEventListener('beforeunload', onUnload);
    return () => window.removeEventListener('beforeunload', onUnload);
  }, []);

  const flushSave = useCallback(async () => {
    for (let i = 0; i < 5 && editVersion.current !== savedVersion.current; i += 1) {
      await saveNow();
      if (savingRef.current) await new Promise((r) => setTimeout(r, 200));
    }
    return editVersion.current === savedVersion.current;
  }, [saveNow]);

  const reloadFromServer = async () => {
    const payload = await getRankingProject(projectId);
    applyPayload(payload, { replaceDoc: true });
    editVersion.current = 0;
    savedVersion.current = 0;
    setSaveState('saved');
  };

  // ---- jobs ----
  const clipJobs = useMemo(() => {
    const map = {};
    jobs
      .filter((j) => j.clip_id && (j.type === 'download' || j.type === 'upload'))
      .forEach((j) => {
        map[j.clip_id] = j;
      });
    return map;
  }, [jobs]);

  const exportActive = ACTIVE.includes(exportJob?.status);
  const hasActive = jobs.some((j) => ACTIVE.includes(j.status)) || exportActive;

  useEffect(() => {
    if (!loaded || !hasActive) return undefined;
    const timer = setInterval(async () => {
      try {
        const payload = await getRankingProject(projectId);
        const finishedClip = payload.jobs.some(
          (j) => j.clip_id && j.status === 'done' && !knownDone.current.has(j.job_id)
        );
        payload.jobs.forEach((j) => {
          if (j.status === 'done') knownDone.current.add(j.job_id);
        });
        setJobs(payload.jobs);
        if (finishedClip) applyPayload(payload, { replaceDoc: false });
        if (exportJob && ACTIVE.includes(exportJob.status)) {
          setExportJob(await getRankingJob(exportJob.job_id));
        }
      } catch {
        /* transient polling failure */
      }
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [loaded, hasActive, projectId, exportJob, applyPayload]);

  // ---- clip actions ----
  const startDownload = async (clip) => {
    setNotice('');
    try {
      const url = (urls[clip.id] ?? clip.source_url ?? '').trim();
      if (url !== clip.source_url) updateClip(clip.id, { source_url: url });
      await new Promise((r) => setTimeout(r, 0));
      await flushSave();
      await startRankingDownload(projectId, clip.id, url);
      await refresh();
    } catch (err) {
      setNotice(errorText(err, 'Could not start download'));
    }
  };

  const startUpload = async (clip, file) => {
    if (!file) return;
    setNotice('');
    try {
      await flushSave();
      await uploadRankingClip(projectId, clip.id, file);
      await refresh();
    } catch (err) {
      setNotice(errorText(err, 'Upload failed'));
    }
  };

  const downloadAll = async () => {
    for (const clip of doc.clips) {
      const url = (urls[clip.id] ?? clip.source_url ?? '').trim();
      if (url && !clip.media && !ACTIVE.includes(clipJobs[clip.id]?.status)) {
        await startDownload(clip);
      }
    }
  };

  const cancelClipJob = async (job) => {
    await cancelRankingJob(job.job_id);
    await refresh();
  };

  const setRank = (clipId, rank) =>
    edit((d) => {
      const target = d.clips.find((c) => c.id === clipId);
      const owner = d.clips.find((c) => c.rank === rank);
      return {
        ...d,
        clips: d.clips.map((c) => {
          if (c.id === clipId) return { ...c, rank };
          if (owner && c.id === owner.id) return { ...c, rank: target.rank };
          return c;
        }),
      };
    });

  const moveClip = (clipId, targetId) => {
    if (clipId === targetId) return;
    edit((d) => {
      const list = [...d.clips].sort((a, b) => a.playback_order - b.playback_order);
      const from = list.findIndex((c) => c.id === clipId);
      const to = list.findIndex((c) => c.id === targetId);
      const [item] = list.splice(from, 1);
      list.splice(to, 0, item);
      const positions = new Map(list.map((c, i) => [c.id, i + 1]));
      return { ...d, clips: d.clips.map((c) => ({ ...c, playback_order: positions.get(c.id) })) };
    });
  };

  const stepClip = (clip, delta) => {
    const list = [...doc.clips].sort((a, b) => a.playback_order - b.playback_order);
    const index = list.findIndex((c) => c.id === clip.id) + delta;
    if (index >= 0 && index < list.length) moveClip(clip.id, list[index].id);
  };

  const applyOrderPreset = (preset) =>
    edit((d) => {
      const byRank = [...d.clips].sort((a, b) => a.rank - b.rank);
      const list = preset === 'countdown' ? [...byRank].reverse() : byRank;
      const positions = new Map(list.map((c, i) => [c.id, i + 1]));
      return { ...d, clips: d.clips.map((c) => ({ ...c, playback_order: positions.get(c.id) })) };
    });

  const addClip = () => {
    if (doc.clips.length >= 10) return;
    const id = Math.random().toString(16).slice(2, 14).padEnd(12, '0');
    edit((d) => ({
      ...d,
      clips: [
        ...d.clips,
        {
          id,
          rank: d.clips.length + 1,
          playback_order: d.clips.length + 1,
          name: '',
          source_url: '',
          provider: null,
          asset_id: null,
          media: null,
          source_generation: 0,
          trim_in: 0,
          trim_out: null,
          fit: 'fill',
          focal_x: 0.5,
          focal_y: 0.5,
          zoom: 1,
          fit_background: '#000000',
          volume: 1,
          muted: false,
        },
      ],
    }));
    setSelectedId(id);
  };

  const removeClip = (clip) => {
    if (doc.clips.length <= 2) return;
    if (clip.media && !window.confirm('Remove this clip and its attached video?')) return;
    edit((d) => {
      const rest = d.clips.filter((c) => c.id !== clip.id);
      const renum = (key) => {
        const sorted = [...rest].sort((a, b) => a[key] - b[key]);
        return new Map(sorted.map((c, i) => [c.id, i + 1]));
      };
      const ranks = renum('rank');
      const orders = renum('playback_order');
      return {
        ...d,
        clips: rest.map((c) => ({ ...c, rank: ranks.get(c.id), playback_order: orders.get(c.id) })),
      };
    });
    if (selectedId === clip.id) setSelectedId(null);
  };

  // ---- derived data ----
  const schedule = useMemo(() => (doc ? buildSchedule(doc.clips) : null), [doc]);
  const segmentIndex = schedule ? segmentIndexAtFrame(schedule, frame) : 0;
  const segment = schedule?.segments[segmentIndex];
  const activeClip = segment?.clip;
  const activeMedia = activeClip ? media[activeClip.id] : null;
  const viewport = doc ? viewportFor(doc.canvas.preset) : [0, 0, 1, 1];
  const selectedClip = doc?.clips.find((c) => c.id === selectedId) ?? null;

  // ---- overlay preview (server-rendered for exact fidelity) ----
  const overlayKey = doc ? `${JSON.stringify({ ...doc, revision: 0 })}|${segmentIndex}` : '';
  useEffect(() => {
    if (!docRef.current) return undefined;
    let stale = false;
    const timer = setTimeout(async () => {
      try {
        const blob = await fetchRankingOverlay(docRef.current, segmentIndex);
        if (stale) return;
        const objectUrl = URL.createObjectURL(blob);
        setOverlayUrl((prev) => {
          if (prev) URL.revokeObjectURL(prev);
          return objectUrl;
        });
      } catch {
        /* keep previous overlay while the draft is invalid */
      }
    }, 250);
    return () => {
      stale = true;
      clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [overlayKey]);

  // ---- serial preview playback ----
  const seekFrame = useCallback(
    (target) => {
      if (!schedule) return;
      const clamped = Math.max(0, Math.min(target, schedule.totalFrames - 1));
      const seg = schedule.segments[segmentIndexAtFrame(schedule, clamped)];
      const target_t = seg.clip.trim_in + (clamped - seg.startFrame) / FPS;
      frameRef.current = clamped;
      setFrame(Math.floor(clamped));
      const video = videoRef.current;
      if (video && video.dataset.clip === seg.clipId && video.readyState >= 1) {
        video.currentTime = target_t;
        pendingSeek.current = null;
      } else {
        pendingSeek.current = target_t;
      }
    },
    [schedule]
  );

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    if (playing && activeMedia?.available) video.play().catch(() => {});
    else video.pause();
  }, [playing, activeMedia?.available, activeClip?.id]);

  useEffect(() => {
    if (!playing || !schedule) return undefined;
    let raf;
    lastTickRef.current = performance.now();
    const tick = (now) => {
      const seg = schedule.segments[segmentIndexAtFrame(schedule, frameRef.current)];
      const video = videoRef.current;
      const live =
        seg.ready && media[seg.clipId]?.available && video && video.dataset.clip === seg.clipId;
      let next = frameRef.current;
      if (live) {
        if (video.readyState >= 2 && pendingSeek.current == null) {
          next = seg.startFrame + Math.max(0, (video.currentTime - seg.clip.trim_in) * FPS);
        }
      } else {
        next += ((now - lastTickRef.current) / 1000) * FPS;
      }
      lastTickRef.current = now;
      const end = seg.startFrame + seg.frames;
      if (next >= end) {
        if (end >= schedule.totalFrames) {
          setPlaying(false);
          frameRef.current = schedule.totalFrames - 1;
          setFrame(schedule.totalFrames - 1);
          return;
        }
        seekFrame(end);
      } else if (Math.floor(next) !== Math.floor(frameRef.current)) {
        frameRef.current = next;
        setFrame(Math.floor(next));
      } else {
        frameRef.current = next;
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [playing, schedule, media, seekFrame]);

  const onVideoLoaded = (event) => {
    const video = event.currentTarget;
    if (pendingSeek.current != null) {
      video.currentTime = pendingSeek.current;
      pendingSeek.current = null;
    } else if (activeClip && segment) {
      video.currentTime = activeClip.trim_in + (frameRef.current - segment.startFrame) / FPS;
    }
    video.volume = Math.min(1, activeClip?.volume ?? 1);
    video.muted = !!activeClip?.muted;
    if (playing) video.play().catch(() => {});
  };

  // ---- export ----
  const exportBlockers = useMemo(() => {
    const list = issues.map((i) => i.message);
    if (saveState === 'invalid') list.push(saveMessage || 'Fix invalid settings');
    if (saveState === 'conflict') list.push('Resolve the save conflict');
    return list;
  }, [issues, saveState, saveMessage]);

  const startExport = async (preview) => {
    setExportError('');
    const ok = await flushSave();
    if (!ok) {
      setExportError('Could not save latest edits');
      return;
    }
    try {
      setExportJob(await startRankingRender(projectId, revisionRef.current, { preview }));
    } catch (err) {
      setExportError(errorText(err, 'Could not start render'));
    }
  };

  const exportOutdated =
    exportJob?.status === 'done' &&
    exportJob.revision != null &&
    exportJob.revision !== revisionRef.current;

  const accentSelection = (color) => {
    const input = headingInput.current;
    if (!input) return;
    const start = input.selectionStart ?? 0;
    const end = input.selectionEnd ?? 0;
    if (end <= start) return;
    updateHeading({ runs: applyAccent(doc.heading.runs, start, end, color) });
  };

  if (loadError) {
    return (
      <div className={styles.fatal}>
        <p>{loadError}</p>
        <button type="button" onClick={onExit}>Back</button>
      </div>
    );
  }
  if (!loaded || !doc) return <div className={styles.fatal}>Loading ranking project…</div>;

  const stageScale = 0.3;
  const saveLabel = {
    saved: 'Saved',
    saving: 'Saving…',
    error: 'Save failed',
    invalid: 'Not saved: invalid',
    conflict: 'Conflict',
  }[saveState];
  const ordered = [...doc.clips].sort((a, b) => a.playback_order - b.playback_order);

  return (
    <div className={styles.root}>
      <header className={styles.topbar}>
        <button
          type="button"
          onClick={async () => {
            await flushSave();
            onExit();
          }}
        >
          ← Back
        </button>
        <input
          className={styles.nameInput}
          value={projectName}
          onChange={(e) => {
            setProjectName(e.target.value);
            editVersion.current += 1;
            setSaveState('saving');
          }}
          aria-label="Project name"
        />
        <span className={`${styles.status} ${styles[saveState]}`} title={saveMessage}>
          {saveLabel}
        </span>
        {saveState === 'error' && (
          <button type="button" onClick={saveNow}>Retry</button>
        )}
      </header>

      {saveState === 'conflict' && (
        <div className={styles.banner}>
          This project changed elsewhere.{' '}
          <button type="button" onClick={reloadFromServer}>Reload latest (discard my edits)</button>
        </div>
      )}
      {saveState === 'invalid' && <div className={styles.banner}>{saveMessage}</div>}
      {notice && <div className={styles.banner}>{notice}</div>}

      <nav className={styles.tabs}>
        {['clips', 'preview', 'design'].map((t) => (
          <button key={t} type="button" className={tab === t ? styles.tabActive : ''} onClick={() => setTab(t)}>
            {t}
          </button>
        ))}
      </nav>

      <div className={styles.panes}>
        <section className={`${styles.pane} ${tab === 'clips' ? styles.show : ''}`}>
          <div className={styles.toolbar}>
            <button type="button" onClick={() => applyOrderPreset('rank')}>Play in rank order</button>
            <button type="button" onClick={() => applyOrderPreset('countdown')}>Countdown</button>
            <button type="button" onClick={downloadAll}>Download all</button>
            <button type="button" onClick={addClip} disabled={doc.clips.length >= 10}>+ Add clip</button>
          </div>
          {ordered.map((clip, index) => {
            const job = clipJobs[clip.id];
            const busy = ACTIVE.includes(job?.status);
            const info = media[clip.id];
            const out = resolvedOut(clip);
            return (
              <div
                key={clip.id}
                className={`${styles.card} ${selectedId === clip.id ? styles.selected : ''}`}
                draggable
                onDragStart={() => setDragId(clip.id)}
                onDragOver={(e) => e.preventDefault()}
                onDrop={() => {
                  if (dragId) moveClip(dragId, clip.id);
                  setDragId(null);
                }}
                onClick={() => setSelectedId(clip.id)}
              >
                <div className={styles.cardHead}>
                  <strong>#{clip.rank}</strong>
                  <span className={styles.muted}>plays {index + 1}</span>
                  <select value={clip.rank} onChange={(e) => setRank(clip.id, Number(e.target.value))} aria-label="Rank">
                    {doc.clips.map((_, i) => (
                      <option key={i + 1} value={i + 1}>Rank {i + 1}</option>
                    ))}
                  </select>
                  <button type="button" onClick={() => stepClip(clip, -1)} disabled={index === 0} aria-label="Play earlier">↑</button>
                  <button type="button" onClick={() => stepClip(clip, 1)} disabled={index === ordered.length - 1} aria-label="Play later">↓</button>
                  <button type="button" onClick={() => removeClip(clip)} disabled={doc.clips.length <= 2}>Remove</button>
                </div>
                <Field label="Name">
                  <input value={clip.name} maxLength={120} placeholder="Shown in the ranking" onChange={(e) => updateClip(clip.id, { name: e.target.value })} />
                </Field>
                <Field label="YouTube / Instagram link">
                  <input
                    value={urls[clip.id] ?? clip.source_url}
                    placeholder="https://…"
                    onChange={(e) => setUrls((u) => ({ ...u, [clip.id]: e.target.value }))}
                  />
                </Field>
                <div className={styles.row}>
                  <button type="button" disabled={busy || !(urls[clip.id] ?? clip.source_url)} onClick={() => startDownload(clip)}>
                    {clip.media ? 'Replace via link' : 'Download'}
                  </button>
                  <label className={styles.fileButton}>
                    Upload file
                    <input
                      type="file"
                      accept="video/*"
                      hidden
                      disabled={busy}
                      onChange={(e) => {
                        startUpload(clip, e.target.files[0]);
                        e.target.value = '';
                      }}
                    />
                  </label>
                </div>
                {job && busy && (
                  <div className={styles.progress}>
                    <progress value={job.progress} max="1" /> {job.phase}
                    <button type="button" onClick={() => cancelClipJob(job)}>Cancel</button>
                  </div>
                )}
                {job?.status === 'error' && !busy && <div className={styles.error}>{job.error}</div>}
                {info?.available && clip.media ? (
                  <div className={styles.trim}>
                    <span className={styles.muted}>
                      {info.filename} · {clip.media.width}×{clip.media.height} · {clip.media.duration.toFixed(1)}s
                      {!clip.media.has_audio && ' · no audio'}
                    </span>
                    <Field label="In (s)">
                      <input type="number" min="0" step="0.1" value={clip.trim_in} onChange={(e) => updateClip(clip.id, { trim_in: Math.max(0, Number(e.target.value) || 0) })} />
                    </Field>
                    <Field label="Out (s)">
                      <input
                        type="number"
                        min="0"
                        step="0.1"
                        value={clip.trim_out ?? ''}
                        placeholder={clip.media.duration.toFixed(1)}
                        onChange={(e) => updateClip(clip.id, { trim_out: e.target.value === '' ? null : Number(e.target.value) })}
                      />
                    </Field>
                    <span className={styles.muted}>Length {out != null ? (out - clip.trim_in).toFixed(1) : '–'}s</span>
                    <label>
                      <input type="checkbox" checked={clip.muted} onChange={(e) => updateClip(clip.id, { muted: e.target.checked })} /> Mute
                    </label>
                    <Field label={`Volume ${Math.round(clip.volume * 100)}%`}>
                      <input type="range" min="0" max="2" step="0.05" value={clip.volume} onChange={(e) => updateClip(clip.id, { volume: Number(e.target.value) })} />
                    </Field>
                  </div>
                ) : (
                  !busy && <div className={styles.muted}>No video attached yet</div>
                )}
              </div>
            );
          })}
        </section>

        <section className={`${styles.pane} ${tab === 'preview' ? styles.show : ''}`}>
          <div className={styles.stageWrap} style={{ width: CANVAS_WIDTH * stageScale, height: CANVAS_HEIGHT * stageScale }}>
            <div
              className={styles.stage}
              style={{ width: CANVAS_WIDTH, height: CANVAS_HEIGHT, transform: `scale(${stageScale})`, background: doc.canvas.background }}
            >
              {activeClip && activeMedia?.available && activeClip.media && (
                <div
                  className={styles.viewport}
                  style={{
                    left: viewport[0],
                    top: viewport[1],
                    width: viewport[2],
                    height: viewport[3],
                    background: activeClip.fit === 'fit' ? activeClip.fit_background : 'transparent',
                  }}
                >
                  <video
                    key={activeClip.id}
                    ref={videoRef}
                    data-clip={activeClip.id}
                    src={getAbsoluteAPIURL(activeMedia.file_url)}
                    playsInline
                    preload="auto"
                    onLoadedMetadata={onVideoLoaded}
                    style={{
                      position: 'absolute',
                      maxWidth: 'none',
                      ...Object.fromEntries(
                        Object.entries(framingBox(activeClip, viewport)).map(([k, v]) => [k, `${v}px`])
                      ),
                    }}
                  />
                </div>
              )}
              {overlayUrl && <img className={styles.overlay} src={overlayUrl} alt="" draggable={false} />}
              {guides && <div className={styles.safe} />}
            </div>
          </div>
          <div className={styles.transport}>
            <button type="button" onClick={() => setPlaying((p) => !p)}>{playing ? 'Pause' : 'Play'}</button>
            <input
              type="range"
              min="0"
              max={Math.max(0, schedule.totalFrames - 1)}
              value={Math.floor(frame)}
              onChange={(e) => {
                setPlaying(false);
                seekFrame(Number(e.target.value));
              }}
              aria-label="Seek"
            />
            <span className={styles.muted}>{(frame / FPS).toFixed(1)} / {schedule.totalSeconds.toFixed(1)}s</span>
            <label>
              <input type="checkbox" checked={guides} onChange={(e) => setGuides(e.target.checked)} /> Safe area
            </label>
          </div>
          {segment && !segment.ready && (
            <div className={styles.muted}>Slot {activeClip.rank} has no video yet (1s placeholder).</div>
          )}

          <div className={styles.exportBox}>
            <div className={styles.row}>
              <button type="button" disabled={exportActive || exportBlockers.length > 0} onClick={() => startExport(true)}>Render preview</button>
              <button type="button" disabled={exportActive || exportBlockers.length > 0} onClick={() => startExport(false)}>Export MP4</button>
            </div>
            {exportBlockers.length > 0 && (
              <ul className={styles.blockers}>
                {exportBlockers.map((b, i) => <li key={i}>{b}</li>)}
              </ul>
            )}
            {exportActive && (
              <div className={styles.progress}>
                <progress value={exportJob.progress} max="1" /> {exportJob.phase}
                <button
                  type="button"
                  onClick={() =>
                    cancelRankingJob(exportJob.job_id)
                      .then(() => getRankingJob(exportJob.job_id))
                      .then(setExportJob)
                  }
                >
                  Cancel
                </button>
              </div>
            )}
            {exportJob?.status === 'error' && <div className={styles.error}>{exportJob.error}</div>}
            {exportJob?.status === 'cancelled' && <div className={styles.muted}>Render cancelled.</div>}
            {exportError && <div className={styles.error}>{exportError}</div>}
            {exportJob?.status === 'done' && exportJob.result?.output_url && (
              <div>
                <video className={styles.result} src={getAbsoluteAPIURL(exportJob.result.output_url)} controls />
                <div className={styles.row}>
                  <span>
                    {exportJob.type === 'preview' ? 'Preview' : 'Export'} of revision{' '}
                    {exportJob.result.revision ?? exportJob.revision}
                    {exportOutdated && ' (earlier version — project has changed)'}
                  </span>
                  <a href={getAbsoluteAPIURL(exportJob.result.output_url)} download={exportJob.result.filename}>Download</a>
                </div>
              </div>
            )}
          </div>
        </section>

        <section className={`${styles.pane} ${tab === 'design' ? styles.show : ''}`}>
          <h3>Heading</h3>
          <Field label="Text">
            <input
              ref={headingInput}
              value={runsText(doc.heading.runs)}
              maxLength={200}
              onChange={(e) => updateHeading({ runs: editRunsText(doc.heading.runs, e.target.value) })}
            />
          </Field>
          <div className={styles.row}>
            <span className={styles.muted}>Select text above, then:</span>
            <input type="color" defaultValue="#ffd400" onChange={(e) => accentSelection(e.target.value)} aria-label="Accent colour" />
            <button type="button" onClick={() => accentSelection(null)}>Clear accent</button>
          </div>
          <div className={styles.grid}>
            <Field label="Font">
              <select value={doc.heading.font} onChange={(e) => updateHeading({ font: e.target.value })}>
                {FONTS.map((f) => <option key={f}>{f}</option>)}
              </select>
            </Field>
            <Field label="Size"><input type="number" min="24" max="160" value={doc.heading.size} onChange={(e) => updateHeading({ size: Number(e.target.value) })} /></Field>
            <Field label="Fill"><input type="color" value={doc.heading.fill} onChange={(e) => updateHeading({ fill: e.target.value })} /></Field>
            <Field label="Outline"><input type="color" value={doc.heading.outline_color} onChange={(e) => updateHeading({ outline_color: e.target.value })} /></Field>
            <Field label="Outline width"><input type="number" min="0" max="20" value={doc.heading.outline_width} onChange={(e) => updateHeading({ outline_width: Number(e.target.value) })} /></Field>
            <Field label="Align">
              <select value={doc.heading.align} onChange={(e) => updateHeading({ align: e.target.value })}>
                {['left', 'center', 'right'].map((a) => <option key={a}>{a}</option>)}
              </select>
            </Field>
            <Field label="Vertical position"><input type="number" min="0" max="1800" value={doc.heading.y} onChange={(e) => updateHeading({ y: Number(e.target.value) })} /></Field>
            <Field label="Backing"><input type="color" value={doc.heading.backing_color} onChange={(e) => updateHeading({ backing_color: e.target.value })} /></Field>
            <Field label={`Backing opacity ${Math.round(doc.heading.backing_opacity * 100)}%`}><input type="range" min="0" max="1" step="0.05" value={doc.heading.backing_opacity} onChange={(e) => updateHeading({ backing_opacity: Number(e.target.value) })} /></Field>
            <label><input type="checkbox" checked={doc.heading.shadow} onChange={(e) => updateHeading({ shadow: e.target.checked })} /> Shadow</label>
          </div>

          <h3>Ranking list</h3>
          <div className={styles.grid}>
            <Field label="Font">
              <select value={doc.ranking.font} onChange={(e) => updateRanking({ font: e.target.value })}>
                {FONTS.map((f) => <option key={f}>{f}</option>)}
              </select>
            </Field>
            <Field label="Number size"><input type="number" min="48" max="200" value={doc.ranking.number_size} onChange={(e) => updateRanking({ number_size: Number(e.target.value) })} /></Field>
            <Field label="Name size"><input type="number" min="32" max="120" value={doc.ranking.title_size} onChange={(e) => updateRanking({ title_size: Number(e.target.value) })} /></Field>
            <Field label="Number colour"><input type="color" value={doc.ranking.number_color} onChange={(e) => updateRanking({ number_color: e.target.value })} /></Field>
            <Field label="Name colour"><input type="color" value={doc.ranking.title_color} onChange={(e) => updateRanking({ title_color: e.target.value })} /></Field>
            <Field label="Current clip colour"><input type="color" value={doc.ranking.active_color} onChange={(e) => updateRanking({ active_color: e.target.value })} /></Field>
            <Field label="Outline"><input type="color" value={doc.ranking.outline_color} onChange={(e) => updateRanking({ outline_color: e.target.value })} /></Field>
            <Field label="Outline width"><input type="number" min="0" max="20" value={doc.ranking.outline_width} onChange={(e) => updateRanking({ outline_width: Number(e.target.value) })} /></Field>
            <Field label="Left"><input type="number" min="0" max="600" value={doc.ranking.left} onChange={(e) => updateRanking({ left: Number(e.target.value) })} /></Field>
            <Field label="Name width"><input type="number" min="200" max="900" value={doc.ranking.title_width} onChange={(e) => updateRanking({ title_width: Number(e.target.value) })} /></Field>
            <Field label="Top"><input type="number" min="0" max="1700" value={doc.ranking.top} onChange={(e) => updateRanking({ top: Number(e.target.value) })} /></Field>
            <Field label="Bottom"><input type="number" min="200" max="1920" value={doc.ranking.bottom} onChange={(e) => updateRanking({ bottom: Number(e.target.value) })} /></Field>
            <label><input type="checkbox" checked={doc.ranking.shadow} onChange={(e) => updateRanking({ shadow: e.target.checked })} /> Shadow</label>
          </div>

          <h3>Layout</h3>
          <div className={styles.grid}>
            <Field label="Footage layout">
              <select value={doc.canvas.preset} onChange={(e) => updateCanvas({ preset: e.target.value })}>
                <option value="header_band">Header band</option>
                <option value="full_frame">Full frame</option>
              </select>
            </Field>
            <Field label="Background"><input type="color" value={doc.canvas.background} onChange={(e) => updateCanvas({ background: e.target.value })} /></Field>
          </div>

          <h3>Framing{selectedClip ? ` — rank ${selectedClip.rank}` : ''}</h3>
          {selectedClip?.media ? (
            <div className={styles.grid}>
              <Field label="Fit">
                <select value={selectedClip.fit} onChange={(e) => updateClip(selectedClip.id, { fit: e.target.value })}>
                  <option value="fill">Fill (crop)</option>
                  <option value="fit">Fit (bars)</option>
                </select>
              </Field>
              {selectedClip.fit === 'fill' ? (
                <>
                  <Field label="Horizontal focus"><input type="range" min="0" max="1" step="0.01" value={selectedClip.focal_x} onChange={(e) => updateClip(selectedClip.id, { focal_x: Number(e.target.value) })} /></Field>
                  <Field label="Vertical focus"><input type="range" min="0" max="1" step="0.01" value={selectedClip.focal_y} onChange={(e) => updateClip(selectedClip.id, { focal_y: Number(e.target.value) })} /></Field>
                  <Field label={`Zoom ${selectedClip.zoom.toFixed(2)}x`}><input type="range" min="1" max="4" step="0.05" value={selectedClip.zoom} onChange={(e) => updateClip(selectedClip.id, { zoom: Number(e.target.value) })} /></Field>
                </>
              ) : (
                <Field label="Bar colour"><input type="color" value={selectedClip.fit_background} onChange={(e) => updateClip(selectedClip.id, { fit_background: e.target.value })} /></Field>
              )}
            </div>
          ) : (
            <p className={styles.muted}>Select a clip with video attached to adjust framing.</p>
          )}
        </section>
      </div>
    </div>
  );
}
