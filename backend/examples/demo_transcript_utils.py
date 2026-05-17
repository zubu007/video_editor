"""Example script demonstrating transcript utility functions."""

import sys
from pathlib import Path

# Add parent directory to path so we can import from utils
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils import words_to_sentences


def main() -> None:
    """Demonstrate word-to-sentence conversion."""
    # Example word-level transcript (as returned by extract_transcript_as_words)
    words = [
        {"word": "Hello ", "start": 0.0, "end": 0.5},
        {"word": "world.", "start": 0.5, "end": 1.0},
        {"word": "This ", "start": 1.2, "end": 1.5},
        {"word": "is ", "start": 1.5, "end": 1.7},
        {"word": "a ", "start": 1.7, "end": 1.9},
        {"word": "test ", "start": 1.9, "end": 2.1},
        {"word": "transcript.", "start": 2.1, "end": 2.8},
        {"word": "How ", "start": 3.0, "end": 3.2},
        {"word": "are ", "start": 3.2, "end": 3.4},
        {"word": "you?", "start": 3.4, "end": 3.8},
    ]

    print("Original word-level transcript:")
    print("-" * 60)
    for word in words:
        print(f"[{word['start']:.2f}s -> {word['end']:.2f}s] {word['word']}")

    # Convert to sentences
    sentences = words_to_sentences(words)

    print("\nConverted to sentence-level transcript:")
    print("-" * 60)
    for sentence in sentences:
        print(f"[{sentence['start']:.2f}s -> {sentence['end']:.2f}s] {sentence['text']}")

    print("\nSummary:")
    print(f"Total words: {len(words)}")
    print(f"Total sentences: {len(sentences)}")


if __name__ == "__main__":
    main()
