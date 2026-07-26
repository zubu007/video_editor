import { useMemo } from 'react';
import { groupWordsIntoPages, findActiveCaption } from '../../utils/captionPages';
import styles from './CaptionOverlay.module.css';

// Live CSS approximation of the burned-in captions: the exact render happens
// server-side with libass, but this mirrors the same paging, colours, active
// word highlight and pop so styles can be previewed instantly while scrubbing.
export default function CaptionOverlay({ words, style, wordsPerLine, currentTime }) {
  const pages = useMemo(
    () =>
      groupWordsIntoPages(words, {
        maxWords: wordsPerLine || style.max_words_per_line,
      }),
    [words, wordsPerLine, style.max_words_per_line]
  );

  const active = findActiveCaption(pages, currentTime);
  if (!active) return null;

  const wordColour = (index) => {
    if (index === active.activeIndex && style.highlight_colour) {
      return style.highlight_colour;
    }
    if (style.word_colours.length > 0) {
      return style.word_colours[index % style.word_colours.length];
    }
    return style.text_colour;
  };

  return (
    <div className={styles.overlay} aria-hidden="true">
      <div
        className={styles.caption}
        style={{
          fontFamily: `'${style.font_family}', 'Arial Black', Impact, sans-serif`,
          fontSize: `${style.font_scale * 100}cqh`,
          bottom: `${style.margin_v_scale * 100}%`,
          textTransform: style.uppercase ? 'uppercase' : 'none',
          '--outline-colour': style.outline_colour,
          '--outline-width': `${style.outline_scale}em`,
          '--shadow-depth': `${style.shadow_scale * 2}em`,
        }}
      >
        {active.page.words.map((word, index) => (
          <span
            key={`${word.start}-${index}`}
            className={`${styles.word} ${
              index === active.activeIndex && style.pop_scale ? styles.popped : ''
            }`}
            style={{
              color: wordColour(index),
              '--pop-scale': style.pop_scale ? style.pop_scale / 100 : 1,
            }}
          >
            {word.word}
          </span>
        ))}
      </div>
    </div>
  );
}
