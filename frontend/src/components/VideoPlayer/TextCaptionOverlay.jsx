import { useMemo } from 'react';
import styles from './TextCaptionOverlay.module.css';

// Mirror of the backend typewriter timing (text_caption.py): reveal speed and
// bounds must match so the live preview streams at the same rate as the burn.
const CHARS_PER_SECOND = 28;
const MIN_REVEAL_SECONDS = 0.3;

function revealSeconds(text, span, override) {
  const target = override && override > 0 ? override : text.length / CHARS_PER_SECOND;
  return Math.max(MIN_REVEAL_SECONDS, Math.min(target, span * 0.85));
}

// Live CSS approximation of the burned-in streaming notes: shows each active
// caption's text revealed character-by-character up to the playhead, with a
// blinking caret while it's still typing.
export default function TextCaptionOverlay({ captions, currentTime }) {
  const active = useMemo(() => {
    return (captions || [])
      .filter((caption) => caption.enabled !== false)
      .map((caption) => {
        const text = String(caption.metadata?.text || '');
        const span = caption.end - caption.start;
        if (!text.trim() || span <= 0) return null;
        if (currentTime < caption.start || currentTime >= caption.end) return null;
        const reveal = revealSeconds(text, span, caption.metadata?.reveal_seconds);
        const progress = Math.min(1, (currentTime - caption.start) / reveal);
        const shown = Math.max(1, Math.round(progress * text.length));
        return {
          id: caption.id,
          position: caption.metadata?.position || 'bottom',
          text: text.slice(0, shown),
          typing: progress < 1,
        };
      })
      .filter(Boolean);
  }, [captions, currentTime]);

  if (active.length === 0) return null;

  return (
    <div className={styles.overlay} aria-hidden="true">
      {active.map((caption) => (
        <div
          key={caption.id}
          className={`${styles.caption} ${styles[caption.position] || styles.bottom}`}
        >
          <span className={styles.text}>
            {caption.text}
            {caption.typing && <span className={styles.caret} />}
          </span>
        </div>
      ))}
    </div>
  );
}
