import { useEffect, useState } from 'react';
import { detectGpu, getOcrEngines } from '../../services/api';
import styles from './SettingsModal.module.css';

// Shown while the engine list loads (and if the backend is unreachable), so
// the picker always renders. Availability is unknown until the fetch lands.
const FALLBACK_OCR_ENGINES = [
  { name: 'tesseract', label: 'Tesseract', available: true, detail: '', description: '' },
  { name: 'paddleocr', label: 'PaddleOCR', available: true, detail: '', description: '' },
  { name: 'easyocr', label: 'EasyOCR', available: true, detail: '', description: '' },
];

function Toggle({ id, checked, onChange, label, description }) {
  return (
    <label className={styles.toggleRow} htmlFor={id}>
      <span className={styles.toggleText}>
        <span className={styles.toggleLabel}>{label}</span>
        {description && <span className={styles.toggleDescription}>{description}</span>}
      </span>
      <input
        id={id}
        type="checkbox"
        role="switch"
        className={styles.switch}
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
      />
    </label>
  );
}

/**
 * Settings popup. Mount it only while open (e.g. `{open && <SettingsModal .../>}`) so
 * transient detection state resets each time it is opened.
 */
export default function SettingsModal({ onClose, settings, updateSetting }) {
  const [gpuState, setGpuState] = useState({ status: 'idle', data: null, error: null });
  const [ocrEngines, setOcrEngines] = useState(FALLBACK_OCR_ENGINES);
  const [ocrEnginesError, setOcrEnginesError] = useState(null);

  // Load the OCR engine list (with server-side availability) once per open.
  useEffect(() => {
    let cancelled = false;
    getOcrEngines()
      .then((data) => {
        if (!cancelled && data.engines?.length) setOcrEngines(data.engines);
      })
      .catch(() => {
        if (!cancelled) {
          setOcrEnginesError('Could not check engine availability on the server.');
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const selectedOcrEngine =
    ocrEngines.find((engine) => engine.name === settings.ocrEngine) || ocrEngines[0];

  // Close on Escape.
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const handleDetectGpu = async () => {
    setGpuState({ status: 'loading', data: null, error: null });
    try {
      const data = await detectGpu();
      setGpuState({ status: 'done', data, error: null });
      // Convenience: pre-enable only when the tool's venv can actually use the GPU.
      if (data.tool?.available && !settings.useGpu) updateSetting('useGpu', true);
    } catch (err) {
      setGpuState({
        status: 'error',
        data: null,
        error: err.response?.data?.detail || err.message || 'GPU detection failed.',
      });
    }
  };

  return (
    <div className={styles.overlay} onMouseDown={onClose}>
      <div
        className={styles.modal}
        role="dialog"
        aria-modal="true"
        aria-labelledby="settings-title"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className={styles.header}>
          <h2 id="settings-title">Settings</h2>
          <button type="button" className={styles.closeButton} onClick={onClose} aria-label="Close settings">
            ✕
          </button>
        </div>

        <section className={styles.section}>
          <h3 className={styles.sectionTitle}>Appearance</h3>
          <Toggle
            id="setting-dark-mode"
            label="Dark mode"
            description="Use the dark color theme."
            checked={settings.theme === 'dark'}
            onChange={(checked) => updateSetting('theme', checked ? 'dark' : 'light')}
          />
        </section>

        <section className={styles.section}>
          <h3 className={styles.sectionTitle}>Performance</h3>
          <Toggle
            id="setting-use-gpu"
            label="Use GPU for caption removal"
            description="Run AI inpainting on an NVIDIA GPU. Requires the GPU setup (see README); otherwise it falls back to slower CPU."
            checked={settings.useGpu}
            onChange={(checked) => updateSetting('useGpu', checked)}
          />

          <div className={styles.detectRow}>
            <button
              type="button"
              className={styles.secondaryButton}
              onClick={handleDetectGpu}
              disabled={gpuState.status === 'loading'}
            >
              {gpuState.status === 'loading' ? 'Detecting…' : 'Detect GPU'}
            </button>

            {gpuState.status === 'done' && gpuState.data && (
              <div className={styles.detectResult}>
                {/* Host: is an NVIDIA driver/GPU present at all? */}
                <div className={gpuState.data.available ? styles.detectOk : styles.detectMuted}>
                  {gpuState.data.available ? (
                    <>
                      <strong>GPU present:</strong>{' '}
                      {gpuState.data.gpus
                        .map((g) =>
                          g.memory_total_mb ? `${g.name} (${g.memory_total_mb} MiB)` : g.name
                        )
                        .join(', ')}
                    </>
                  ) : (
                    gpuState.data.detail
                  )}
                </div>

                {/* Tool: can the caption-removal venv actually use CUDA? */}
                {gpuState.data.tool && (
                  <div
                    className={
                      gpuState.data.tool.available ? styles.detectOk : styles.detectWarn
                    }
                  >
                    <strong>Caption tool:</strong>{' '}
                    {gpuState.data.tool.available
                      ? `ready on the GPU${
                          gpuState.data.tool.device_name
                            ? ` — ${gpuState.data.tool.device_name}`
                            : ''
                        }`
                      : gpuState.data.tool.detail}
                  </div>
                )}
              </div>
            )}
            {gpuState.status === 'error' && (
              <div className={styles.detectError}>{gpuState.error}</div>
            )}
          </div>
        </section>

        <section className={styles.section}>
          <h3 className={styles.sectionTitle}>Gaming: K/D/A detection</h3>
          <div className={styles.fieldRow}>
            <label className={styles.fieldLabel} htmlFor="setting-ocr-engine">
              OCR engine
            </label>
            <select
              id="setting-ocr-engine"
              className={styles.select}
              value={settings.ocrEngine}
              onChange={(e) => updateSetting('ocrEngine', e.target.value)}
            >
              {ocrEngines.map((engine) => (
                <option key={engine.name} value={engine.name}>
                  {engine.label}
                  {engine.available ? '' : ' (not installed)'}
                </option>
              ))}
            </select>
          </div>
          {selectedOcrEngine && (
            <p className={styles.fieldHint}>
              {selectedOcrEngine.description}
              {!selectedOcrEngine.available && selectedOcrEngine.detail && (
                <span className={styles.detectWarn}>
                  {' '}
                  Unavailable: {selectedOcrEngine.detail}.
                </span>
              )}
            </p>
          )}
          {ocrEnginesError && <p className={styles.fieldHint}>{ocrEnginesError}</p>}
        </section>

        <section className={styles.section}>
          <h3 className={styles.sectionTitle}>AI provider</h3>
          <p className={styles.fieldHint}>
            Used for the editing plan, diagram suggestions and the assistant
            chat. Point it at any OpenAI-compatible API; leave blank to use the
            server&apos;s built-in Groq configuration.
          </p>
          <div className={styles.fieldRow}>
            <label className={styles.fieldLabel} htmlFor="setting-llm-base-url">
              API base URL
            </label>
            <input
              id="setting-llm-base-url"
              type="url"
              className={styles.textInput}
              placeholder="https://api.groq.com/openai/v1"
              value={settings.llmBaseUrl}
              onChange={(e) => updateSetting('llmBaseUrl', e.target.value.trim())}
            />
          </div>
          <div className={styles.fieldRow}>
            <label className={styles.fieldLabel} htmlFor="setting-llm-api-key">
              API key
            </label>
            <input
              id="setting-llm-api-key"
              type="password"
              className={styles.textInput}
              placeholder="Uses the server's key when blank"
              autoComplete="off"
              value={settings.llmApiKey}
              onChange={(e) => updateSetting('llmApiKey', e.target.value.trim())}
            />
          </div>
          <div className={styles.fieldRow}>
            <label className={styles.fieldLabel} htmlFor="setting-llm-model">
              Model
            </label>
            <input
              id="setting-llm-model"
              type="text"
              className={styles.textInput}
              placeholder="llama-3.3-70b-versatile"
              value={settings.llmModel}
              onChange={(e) => updateSetting('llmModel', e.target.value.trim())}
            />
          </div>
          <p className={styles.fieldHint}>
            The key is stored in this browser only and sent with each AI
            request.
          </p>
        </section>
      </div>
    </div>
  );
}
