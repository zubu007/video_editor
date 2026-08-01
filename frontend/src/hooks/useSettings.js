import { useCallback, useEffect, useState } from 'react';

const STORAGE_KEY = 'videoEditorSettings';

export const DEFAULT_SETTINGS = {
  theme: 'light', // 'light' | 'dark'
  useGpu: false, // use GPU for caption removal
  ocrEngine: 'tesseract', // OCR engine for gaming K/D/A detection
  llmBaseUrl: '', // OpenAI-compatible base URL ('' = server default / Groq)
  llmApiKey: '', // API key for the custom LLM provider ('' = server .env key)
  llmModel: '', // model at the custom provider ('' = server default model)
};

/**
 * Read the persisted settings outside React (e.g. from the API layer, so LLM
 * provider and OCR settings apply to requests without prop-drilling).
 * @returns {typeof DEFAULT_SETTINGS}
 */
export function getStoredSettings() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_SETTINGS;
    // Merge so newly added settings keys fall back to their defaults.
    return { ...DEFAULT_SETTINGS, ...JSON.parse(raw) };
  } catch {
    return DEFAULT_SETTINGS;
  }
}

/**
 * Persisted app settings backed by localStorage.
 * @returns {{ settings: typeof DEFAULT_SETTINGS, updateSetting: (key: string, value: any) => void }}
 */
export default function useSettings() {
  const [settings, setSettings] = useState(getStoredSettings);

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
    } catch {
      // Ignore storage failures (e.g. private mode); settings stay in memory.
    }
  }, [settings]);

  const updateSetting = useCallback((key, value) => {
    setSettings((prev) => ({ ...prev, [key]: value }));
  }, []);

  return { settings, updateSetting };
}
