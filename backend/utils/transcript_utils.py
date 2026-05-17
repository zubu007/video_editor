"""Transcript utility functions for converting between different timestamp formats."""

from __future__ import annotations

from typing import Any


def words_to_sentences(
    words: list[dict[str, Any]], sentence_endings: tuple[str, ...] = (".", "?", "!")
) -> list[dict[str, Any]]:
    """Convert word-level timestamps to sentence-level timestamps.

    This function takes a list of word-level transcriptions and groups them
    into sentences based on punctuation marks that typically end sentences.

    Args:
        words: A list of word dictionaries, where each word has:
            - "word" (str): The word text
            - "start" (float): Start timestamp in seconds
            - "end" (float): End timestamp in seconds
        sentence_endings: Tuple of punctuation marks that end sentences.
            Defaults to (".", "?", "!").

    Returns:
        A list of sentence dictionaries, where each sentence has:
            - "text" (str): The complete sentence text
            - "start" (float): Start timestamp of the first word
            - "end" (float): End timestamp of the last word

    Example:
        >>> words = [
        ...     {"word": "Hello ", "start": 0.0, "end": 0.5},
        ...     {"word": "world.", "start": 0.5, "end": 1.0},
        ...     {"word": "How ", "start": 1.2, "end": 1.5},
        ...     {"word": "are ", "start": 1.5, "end": 1.7},
        ...     {"word": "you?", "start": 1.7, "end": 2.0}
        ... ]
        >>> sentences = words_to_sentences(words)
        >>> len(sentences)
        2
        >>> sentences[0]["text"]
        'Hello world.'
        >>> sentences[1]["text"]
        'How are you?'
    """
    if not words:
        return []

    sentences = []
    current_sentence: dict[str, Any] | None = None

    for word in words:
        word_text = word.get("word", "")
        word_start = word.get("start")
        word_end = word.get("end")

        # Skip if word is missing required fields
        if word_start is None or word_end is None:
            continue

        # Initialize a new sentence if we don't have one
        if current_sentence is None:
            current_sentence = {
                "start": word_start,
                "end": word_end,
                "text": word_text,
            }
        else:
            # Extend the current sentence
            current_sentence["end"] = word_end
            current_sentence["text"] += word_text

        # Check if this word ends a sentence
        if any(word_text.rstrip().endswith(ending) for ending in sentence_endings):
            sentences.append(current_sentence)
            current_sentence = None

    # Add any remaining sentence that didn't end with punctuation
    if current_sentence is not None:
        sentences.append(current_sentence)

    return sentences


def sentences_to_words(sentences: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert sentence-level timestamps to word-level timestamps (approximate).

    This is an approximate conversion that splits sentences into words and
    estimates timestamps based on word count distribution. For accurate
    word-level timestamps, use the transcription with word_timestamps=True.

    Args:
        sentences: A list of sentence dictionaries, where each sentence has:
            - "text" (str): The complete sentence text
            - "start" (float): Start timestamp in seconds
            - "end" (float): End timestamp in seconds

    Returns:
        A list of approximate word dictionaries, where each word has:
            - "word" (str): The word text
            - "start" (float): Estimated start timestamp
            - "end" (float): Estimated end timestamp

    Example:
        >>> sentences = [
        ...     {"text": "Hello world.", "start": 0.0, "end": 1.0}
        ... ]
        >>> words = sentences_to_words(sentences)
        >>> len(words)
        2
    """
    if not sentences:
        return []

    words = []

    for sentence in sentences:
        sentence_text = sentence.get("text", "")
        sentence_start = sentence.get("start")
        sentence_end = sentence.get("end")

        # Skip if sentence is missing required fields
        if sentence_start is None or sentence_end is None or not sentence_text:
            continue

        # Split the sentence into words (preserving trailing punctuation)
        word_list = sentence_text.split()
        if not word_list:
            continue

        sentence_duration = sentence_end - sentence_start
        time_per_word = sentence_duration / len(word_list)

        for i, word_text in enumerate(word_list):
            word_start = sentence_start + (i * time_per_word)
            word_end = word_start + time_per_word

            words.append(
                {
                    "word": word_text + " " if i < len(word_list) - 1 else word_text,
                    "start": word_start,
                    "end": word_end,
                }
            )

    return words
