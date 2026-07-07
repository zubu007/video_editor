import { useCallback, useEffect, useRef, useState } from 'react';
import { formatFileSize } from '../../utils/videoUtils';
import styles from './RecordVideo.module.css';

// Ordered by preference: mp4 (Safari, newer Chrome) plays best downstream,
// webm variants cover Chrome/Firefox.
const MIME_CANDIDATES = [
  'video/mp4;codecs="avc1.42E01E,mp4a.40.2"',
  'video/mp4',
  'video/webm;codecs=vp9,opus',
  'video/webm;codecs=vp8,opus',
  'video/webm',
];

function pickSupportedMimeType() {
  if (typeof MediaRecorder === 'undefined') return null;
  return MIME_CANDIDATES.find((type) => MediaRecorder.isTypeSupported(type)) ?? '';
}

function extensionForMimeType(mimeType) {
  return mimeType.includes('mp4') ? 'mp4' : 'webm';
}

function formatElapsed(totalSeconds) {
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
}

function friendlyMediaError(err) {
  if (err?.name === 'NotAllowedError' || err?.name === 'SecurityError') {
    return 'Camera and microphone access was denied. Allow access in your browser and try again.';
  }
  if (err?.name === 'NotFoundError' || err?.name === 'OverconstrainedError') {
    return 'No camera or microphone was found. Connect a device and try again.';
  }
  if (err?.name === 'NotReadableError') {
    return 'The camera is already in use by another application.';
  }
  return 'Could not start the camera. Check your browser permissions and try again.';
}

function RecordVideo({ onVideoSelect }) {
  const [cameras, setCameras] = useState([]);
  const [microphones, setMicrophones] = useState([]);
  const [selectedCameraId, setSelectedCameraId] = useState('');
  const [selectedMicId, setSelectedMicId] = useState('');
  const [isStreamReady, setIsStreamReady] = useState(false);
  const [isRecording, setIsRecording] = useState(false);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [recording, setRecording] = useState(null); // { blob, url, mimeType }
  const [error, setError] = useState(null);

  const previewRef = useRef(null);
  const streamRef = useRef(null);
  const recorderRef = useRef(null);
  const chunksRef = useRef([]);
  const timerRef = useRef(null);
  const handedOffRef = useRef(false);

  const stopStream = useCallback(() => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    setIsStreamReady(false);
  }, []);

  const refreshDeviceLists = useCallback(async () => {
    const devices = await navigator.mediaDevices.enumerateDevices();
    setCameras(devices.filter((device) => device.kind === 'videoinput'));
    setMicrophones(devices.filter((device) => device.kind === 'audioinput'));
  }, []);

  const startStream = useCallback(
    async (cameraId, micId) => {
      stopStream();
      setError(null);
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          video: {
            ...(cameraId ? { deviceId: { exact: cameraId } } : {}),
            width: { ideal: 1920 },
            height: { ideal: 1080 },
          },
          audio: micId ? { deviceId: { exact: micId } } : true,
        });
        streamRef.current = stream;
        if (previewRef.current) {
          previewRef.current.srcObject = stream;
        }
        setIsStreamReady(true);

        // Device labels are only populated once permission has been granted,
        // so the lists are (re)built after getUserMedia succeeds.
        await refreshDeviceLists();
        const videoTrack = stream.getVideoTracks()[0];
        const audioTrack = stream.getAudioTracks()[0];
        setSelectedCameraId(videoTrack?.getSettings().deviceId || '');
        setSelectedMicId(audioTrack?.getSettings().deviceId || '');
      } catch (err) {
        console.error('Error starting camera stream:', err);
        setError(friendlyMediaError(err));
      }
    },
    [stopStream, refreshDeviceLists]
  );

  useEffect(() => {
    startStream('', '');
    navigator.mediaDevices.addEventListener?.('devicechange', refreshDeviceLists);
    return () => {
      navigator.mediaDevices.removeEventListener?.('devicechange', refreshDeviceLists);
      if (recorderRef.current && recorderRef.current.state !== 'inactive') {
        recorderRef.current.stop();
      }
      clearInterval(timerRef.current);
      streamRef.current?.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Re-attach the live stream when switching back from the review player,
  // since the <video> element remounts.
  useEffect(() => {
    if (!recording && previewRef.current && streamRef.current) {
      previewRef.current.srcObject = streamRef.current;
    }
  }, [recording, isStreamReady]);

  useEffect(() => {
    const url = recording?.url;
    return () => {
      // Keep the URL alive when it was handed to the parent for playback.
      if (url && !handedOffRef.current) {
        URL.revokeObjectURL(url);
      }
    };
  }, [recording]);

  const handleCameraChange = (event) => {
    const deviceId = event.target.value;
    setSelectedCameraId(deviceId);
    startStream(deviceId, selectedMicId);
  };

  const handleMicChange = (event) => {
    const deviceId = event.target.value;
    setSelectedMicId(deviceId);
    startStream(selectedCameraId, deviceId);
  };

  const handleStartRecording = () => {
    const stream = streamRef.current;
    if (!stream) return;

    const mimeType = pickSupportedMimeType();
    if (mimeType === null) {
      setError('Recording is not supported in this browser.');
      return;
    }

    chunksRef.current = [];
    let recorder;
    try {
      recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    } catch (err) {
      console.error('Error creating MediaRecorder:', err);
      setError('Could not start recording in this browser.');
      return;
    }

    recorder.ondataavailable = (event) => {
      if (event.data && event.data.size > 0) {
        chunksRef.current.push(event.data);
      }
    };
    recorder.onstop = () => {
      clearInterval(timerRef.current);
      const type = (recorder.mimeType || mimeType || 'video/webm').split(';')[0];
      const blob = new Blob(chunksRef.current, { type });
      chunksRef.current = [];
      setRecording({ blob, url: URL.createObjectURL(blob), mimeType: type });
      setIsRecording(false);
    };

    // A 1s timeslice flushes data periodically so a long take isn't lost
    // if the tab crashes mid-recording.
    recorder.start(1000);
    recorderRef.current = recorder;
    setError(null);
    setIsRecording(true);
    setElapsedSeconds(0);
    timerRef.current = setInterval(() => {
      setElapsedSeconds((seconds) => seconds + 1);
    }, 1000);
  };

  const handleStopRecording = () => {
    if (recorderRef.current && recorderRef.current.state !== 'inactive') {
      recorderRef.current.stop();
    }
  };

  const handleUseRecording = () => {
    if (!recording) return;
    const timestamp = new Date()
      .toISOString()
      .replace(/[:.]/g, '-')
      .slice(0, 19);
    const extension = extensionForMimeType(recording.mimeType);
    const file = new File([recording.blob], `recording-${timestamp}.${extension}`, {
      type: recording.mimeType,
    });
    handedOffRef.current = true;
    stopStream();
    onVideoSelect(file, recording.url);
  };

  const handleDiscard = () => {
    setRecording(null);
    setElapsedSeconds(0);
    if (!streamRef.current) {
      startStream(selectedCameraId, selectedMicId);
    }
  };

  return (
    <div className={styles.recordContainer}>
      <div className={styles.previewWrap}>
        {!recording && (
          <video
            ref={previewRef}
            autoPlay
            playsInline
            muted
            className={`${styles.preview} ${styles.mirrored}`}
          />
        )}
        {recording && (
          <video src={recording.url} controls playsInline className={styles.preview} />
        )}

        {isRecording && (
          <div className={styles.recBadge}>
            <span className={styles.recDot} />
            REC {formatElapsed(elapsedSeconds)}
          </div>
        )}

        {!isStreamReady && !recording && !error && (
          <div className={styles.placeholder}>Starting camera…</div>
        )}
        {error && !recording && <div className={styles.placeholder}>{error}</div>}
      </div>

      <div className={styles.devicesRow}>
        <label className={styles.deviceField}>
          Camera
          <select
            value={selectedCameraId}
            onChange={handleCameraChange}
            disabled={isRecording || Boolean(recording) || cameras.length === 0}
          >
            {cameras.length === 0 && <option value="">No cameras found</option>}
            {cameras.map((device, index) => (
              <option key={device.deviceId || index} value={device.deviceId}>
                {device.label || `Camera ${index + 1}`}
              </option>
            ))}
          </select>
        </label>

        <label className={styles.deviceField}>
          Microphone
          <select
            value={selectedMicId}
            onChange={handleMicChange}
            disabled={isRecording || Boolean(recording) || microphones.length === 0}
          >
            {microphones.length === 0 && <option value="">No microphones found</option>}
            {microphones.map((device, index) => (
              <option key={device.deviceId || index} value={device.deviceId}>
                {device.label || `Microphone ${index + 1}`}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className={styles.controls}>
        {!isRecording && !recording && (
          <button
            type="button"
            className={styles.recordButton}
            onClick={handleStartRecording}
            disabled={!isStreamReady}
          >
            <span className={styles.recordIcon} />
            Start Recording
          </button>
        )}
        {isRecording && (
          <button type="button" className={styles.stopButton} onClick={handleStopRecording}>
            <span className={styles.stopIcon} />
            Stop Recording
          </button>
        )}
        {recording && (
          <>
            <button type="button" className={styles.useButton} onClick={handleUseRecording}>
              Use This Recording
            </button>
            <button type="button" className={styles.discardButton} onClick={handleDiscard}>
              Discard &amp; Re-record
            </button>
          </>
        )}
      </div>

      {recording ? (
        <p className={styles.hint}>
          Recorded {formatElapsed(elapsedSeconds)} · {formatFileSize(recording.blob.size)} ·{' '}
          {recording.mimeType}
        </p>
      ) : (
        <p className={styles.hint}>
          The live preview is mirrored for comfort — the recorded footage is not.
        </p>
      )}

      {error && recording && <div className={styles.error}>{error}</div>}
    </div>
  );
}

export default RecordVideo;
