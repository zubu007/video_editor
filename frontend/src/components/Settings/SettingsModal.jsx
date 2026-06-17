import { useEffect, useState } from 'react';
import { detectGpu } from '../../services/api';
import styles from './SettingsModal.module.css';

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
      </div>
    </div>
  );
}
