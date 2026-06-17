"""Tests for transcript utility functions."""

from __future__ import annotations


from backend.utils.transcript_utils import sentences_to_words, words_to_sentences


class TestWordsToSentences:
    """Tests for words_to_sentences function."""

    def test_basic_conversion(self) -> None:
        """Test basic conversion of words to sentences."""
        words = [
            {"word": "Hello ", "start": 0.0, "end": 0.5},
            {"word": "world.", "start": 0.5, "end": 1.0},
            {"word": "How ", "start": 1.2, "end": 1.5},
            {"word": "are ", "start": 1.5, "end": 1.7},
            {"word": "you?", "start": 1.7, "end": 2.0},
        ]

        sentences = words_to_sentences(words)

        assert len(sentences) == 2
        assert sentences[0]["text"] == "Hello world."
        assert sentences[0]["start"] == 0.0
        assert sentences[0]["end"] == 1.0
        assert sentences[1]["text"] == "How are you?"
        assert sentences[1]["start"] == 1.2
        assert sentences[1]["end"] == 2.0

    def test_multiple_sentence_endings(self) -> None:
        """Test with different sentence ending punctuation."""
        words = [
            {"word": "Hello!", "start": 0.0, "end": 0.5},
            {"word": "What?", "start": 0.6, "end": 1.0},
            {"word": "Okay.", "start": 1.1, "end": 1.5},
        ]

        sentences = words_to_sentences(words)

        assert len(sentences) == 3
        assert sentences[0]["text"] == "Hello!"
        assert sentences[1]["text"] == "What?"
        assert sentences[2]["text"] == "Okay."

    def test_no_sentence_ending(self) -> None:
        """Test when words don't end with punctuation."""
        words = [
            {"word": "Hello ", "start": 0.0, "end": 0.5},
            {"word": "world", "start": 0.5, "end": 1.0},
        ]

        sentences = words_to_sentences(words)

        assert len(sentences) == 1
        assert sentences[0]["text"] == "Hello world"
        assert sentences[0]["start"] == 0.0
        assert sentences[0]["end"] == 1.0

    def test_empty_words_list(self) -> None:
        """Test with empty words list."""
        sentences = words_to_sentences([])
        assert sentences == []

    def test_custom_sentence_endings(self) -> None:
        """Test with custom sentence ending characters."""
        words = [
            {"word": "Hello;", "start": 0.0, "end": 0.5},
            {"word": "world", "start": 0.5, "end": 1.0},
        ]

        sentences = words_to_sentences(words, sentence_endings=(";",))

        assert len(sentences) == 2
        assert sentences[0]["text"] == "Hello;"
        assert sentences[1]["text"] == "world"

    def test_missing_fields(self) -> None:
        """Test with words missing required fields."""
        words = [
            {"word": "Hello ", "start": 0.0, "end": 0.5},
            {"word": "missing", "start": 0.5},  # Missing 'end'
            {"word": "world.", "start": 1.0, "end": 1.5},
        ]

        sentences = words_to_sentences(words)

        # Should skip the word with missing fields
        assert len(sentences) == 1
        assert sentences[0]["text"] == "Hello world."

    def test_single_word_sentence(self) -> None:
        """Test with a single word forming a sentence."""
        words = [{"word": "Stop.", "start": 0.0, "end": 0.5}]

        sentences = words_to_sentences(words)

        assert len(sentences) == 1
        assert sentences[0]["text"] == "Stop."
        assert sentences[0]["start"] == 0.0
        assert sentences[0]["end"] == 0.5

    def test_long_sentence(self) -> None:
        """Test with a long multi-word sentence."""
        words = [
            {"word": "This ", "start": 0.0, "end": 0.2},
            {"word": "is ", "start": 0.2, "end": 0.4},
            {"word": "a ", "start": 0.4, "end": 0.5},
            {"word": "very ", "start": 0.5, "end": 0.7},
            {"word": "long ", "start": 0.7, "end": 0.9},
            {"word": "sentence.", "start": 0.9, "end": 1.5},
        ]

        sentences = words_to_sentences(words)

        assert len(sentences) == 1
        assert sentences[0]["text"] == "This is a very long sentence."
        assert sentences[0]["start"] == 0.0
        assert sentences[0]["end"] == 1.5

    def test_whitespace_handling(self) -> None:
        """Test proper handling of whitespace in words."""
        words = [
            {"word": "Hello  ", "start": 0.0, "end": 0.5},
            {"word": "world. ", "start": 0.5, "end": 1.0},
        ]

        sentences = words_to_sentences(words)

        assert len(sentences) == 1
        # The function should preserve the whitespace as given
        assert sentences[0]["text"] == "Hello  world. "


class TestSentencesToWords:
    """Tests for sentences_to_words function."""

    def test_basic_conversion(self) -> None:
        """Test basic conversion of sentences to words."""
        sentences = [{"text": "Hello world.", "start": 0.0, "end": 1.0}]

        words = sentences_to_words(sentences)

        assert len(words) == 2
        assert words[0]["word"] == "Hello "
        assert words[1]["word"] == "world."
        assert words[0]["start"] == 0.0
        assert words[1]["end"] == 1.0

    def test_multiple_sentences(self) -> None:
        """Test with multiple sentences."""
        sentences = [
            {"text": "Hello world.", "start": 0.0, "end": 1.0},
            {"text": "How are you?", "start": 1.5, "end": 2.5},
        ]

        words = sentences_to_words(sentences)

        assert len(words) == 5
        assert words[0]["word"] == "Hello "
        assert words[1]["word"] == "world."
        assert words[2]["word"] == "How "
        assert words[3]["word"] == "are "
        assert words[4]["word"] == "you?"

    def test_empty_sentences_list(self) -> None:
        """Test with empty sentences list."""
        words = sentences_to_words([])
        assert words == []

    def test_single_word_sentence(self) -> None:
        """Test with a single word sentence."""
        sentences = [{"text": "Stop.", "start": 0.0, "end": 0.5}]

        words = sentences_to_words(sentences)

        assert len(words) == 1
        assert words[0]["word"] == "Stop."
        assert words[0]["start"] == 0.0
        assert words[0]["end"] == 0.5

    def test_missing_fields(self) -> None:
        """Test with sentences missing required fields."""
        sentences = [
            {"text": "Hello world.", "start": 0.0, "end": 1.0},
            {"text": "Missing end", "start": 1.0},  # Missing 'end'
            {"text": "Good morning.", "start": 2.0, "end": 3.0},
        ]

        words = sentences_to_words(sentences)

        # Should skip the sentence with missing fields
        assert len(words) == 4

    def test_timestamp_distribution(self) -> None:
        """Test that timestamps are distributed evenly across words."""
        sentences = [{"text": "One two three", "start": 0.0, "end": 3.0}]

        words = sentences_to_words(sentences)

        assert len(words) == 3
        # Each word should get approximately 1 second
        assert abs(words[0]["end"] - words[0]["start"] - 1.0) < 0.01
        assert abs(words[1]["end"] - words[1]["start"] - 1.0) < 0.01
        assert abs(words[2]["end"] - words[2]["start"] - 1.0) < 0.01

    def test_empty_text(self) -> None:
        """Test with sentence having empty text."""
        sentences = [
            {"text": "", "start": 0.0, "end": 1.0},
            {"text": "Valid sentence.", "start": 1.0, "end": 2.0},
        ]

        words = sentences_to_words(sentences)

        # Should skip the empty sentence
        assert len(words) == 2
        assert words[0]["word"] == "Valid "
        assert words[1]["word"] == "sentence."
