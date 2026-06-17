import { useEffect, useRef, useState } from 'react';
import { removeCaptions, getCaptionRemovalStatus, getAbsoluteAPIURL } from '../../services/api';
import styles from './CaptionTool.module.css';

const POLL_INTERVAL_MS = 3000;

const STATUS_LABEL = {
  pending: 'Queued...',
  running: 'Removing captions (this can take several minutes)...',
};

/**
 * Self-contained tool that starts a caption-removal job for the current video and
 * polls the backend until the cleaned video is ready.
 */
export default function CaptionTool({ fileId, useGpu = false }) {
  const [status, setStatus] = useState('idle'); // idle|pending|running|done|error
  const [result, setResult] = useState(null); // { url, filename }
  const [error, setError] = useState(null);
  const pollRef = useRef(null);

  // Stop polling on unmount. The component is keyed by fileId in App, so switching
  // videos remounts it and resets state without an effect.
  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  const isBusy = status === 'pending' || status === 'running';

  const pollStatus = (jobId) => {
    pollRef.current = setInterval(async () => {
      try {
        const data = await getCaptionRemovalStatus(jobId);
        setStatus(data.status);
        if (data.status === 'done') {
          clearInterval(pollRef.current);
          const filename = data.output_url.split('/').pop();
          setResult({ url: getAbsoluteAPIURL(data.output_url), filename });
        } else if (data.status === 'error') {
          clearInterval(pollRef.current);
          setError(data.error || 'Caption removal failed.');
        }
      } catch (err) {
        clearInterval(pollRef.current);
        setStatus('error');
        setError(err.response?.data?.detail || err.message || 'Failed to check job status.');
      }
    }, POLL_INTERVAL_MS);
  };

  const handleRemove = async () => {
    if (!fileId) return;
    setStatus('pending');
    setResult(null);
    setError(null);
    try {
      const { job_id: jobId } = await removeCaptions(fileId, { useGpu });
      pollStatus(jobId);
    } catch (err) {
      setStatus('error');
      setError(err.response?.data?.detail || err.message || 'Failed to start caption removal.');
    }
  };

  return (
    <section className={styles.panel}>
      <div className={styles.header}>
        <div>
          <h3>Caption Removal</h3>
          <p>Scan the video for burned-in captions and erase them with AI inpainting.</p>
        </div>
        <button
          type="button"
          className={styles.primaryButton}
          onClick={handleRemove}
          disabled={!fileId || isBusy}
        >
          {isBusy ? 'Working...' : 'Remove Captions'}
        </button>
      </div>

      {error && <div className={styles.error}>{error}</div>}

      {isBusy && (
        <div className={styles.status}>
          <span className={styles.spinner} aria-hidden="true" />
          <span>{STATUS_LABEL[status]}</span>
        </div>
      )}

      {status === 'done' && result && (
        <div className={styles.result}>
          <p>Captions removed. The cleaned video is ready.</p>
          <a className={styles.resultLink} href={result.url} target="_blank" rel="noreferrer">
            Download {result.filename}
          </a>
        </div>
      )}
    </section>
  );
}
