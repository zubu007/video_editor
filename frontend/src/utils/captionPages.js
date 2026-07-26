// Client-side mirror of the backend caption layout (backend/features/captions/
// layout.py) so the live preview overlay pages words the same way the final
// burn will: pages break on a word budget, sentence punctuation and speech
// gaps, and each page lingers briefly (or until the next page) so captions
// don't flicker between words.

const DEFAULT_MAX_WORDS = 3;
const DEFAULT_MAX_GAP = 1.0;
const DEFAULT_LINGER = 0.5;
const SENTENCE_END = /[.!?]$/;

/**
 * Split a word-level transcript into caption pages.
 * @param {Array<{start: number, end: number, word: string}>} words - Words in time order
 * @param {{maxWords?: number, maxGap?: number, linger?: number}} [options]
 * @returns {Array<{start: number, end: number, words: Array}>} Caption pages
 */
export function groupWordsIntoPages(
  words,
  { maxWords = DEFAULT_MAX_WORDS, maxGap = DEFAULT_MAX_GAP, linger = DEFAULT_LINGER } = {}
) {
  const groups = [];
  let current = [];
  for (const raw of words || []) {
    const text = String(raw.word ?? '').trim();
    if (!text) continue;
    const word = { start: Number(raw.start), end: Number(raw.end), word: text };
    if (current.length > 0) {
      const previous = current[current.length - 1];
      const gapBreak = word.start - previous.end > maxGap;
      const sentenceBreak = SENTENCE_END.test(previous.word);
      if (current.length >= maxWords || gapBreak || sentenceBreak) {
        groups.push(current);
        current = [];
      }
    }
    current.push(word);
  }
  if (current.length > 0) groups.push(current);

  return groups.map((pageWords, index) => {
    let end = pageWords[pageWords.length - 1].end;
    if (index + 1 < groups.length) {
      const nextStart = groups[index + 1][0].start;
      end = nextStart - end <= linger ? nextStart : end + linger;
    } else {
      end += linger;
    }
    return { start: pageWords[0].start, end, words: pageWords };
  });
}

/**
 * Find the caption page on screen at `time`, plus which word is active.
 * @param {Array<{start: number, end: number, words: Array}>} pages
 * @param {number} time - Playback time in seconds
 * @returns {{page: Object, activeIndex: number}|null} Null when no page is showing
 */
export function findActiveCaption(pages, time) {
  const page = (pages || []).find((p) => time >= p.start && time < p.end);
  if (!page) return null;
  let activeIndex = 0;
  for (let i = 0; i < page.words.length; i += 1) {
    if (time >= page.words[i].start) activeIndex = i;
  }
  return { page, activeIndex };
}
