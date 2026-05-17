import unittest
from backend.features.filler_words.detect import detect_filler_words

class TestFillerWords(unittest.TestCase):

    def test_detect_filler_words(self):
        words = [
            {'word': 'Hello', 'start': 0.0, 'end': 0.5},
            {'word': 'um', 'start': 0.6, 'end': 0.8},
            {'word': 'world', 'start': 0.9, 'end': 1.5},
            {'word': 'ah', 'start': 1.6, 'end': 1.8},
            {'word': 'this', 'start': 1.9, 'end': 2.2},
            {'word': 'is', 'start': 2.3, 'end': 2.5},
            {'word': 'like', 'start': 2.6, 'end': 2.9},
            {'word': 'a', 'start': 3.0, 'end': 3.1},
            {'word': 'test', 'start': 3.2, 'end': 3.5},
        ]

        expected_ranges = [
            {'start': 0.6, 'end': 0.8},
            {'start': 1.6, 'end': 1.8},
            {'start': 2.6, 'end': 2.9},
        ]

        filler_word_ranges = detect_filler_words(words)
        self.assertEqual(filler_word_ranges, expected_ranges)

if __name__ == '__main__':
    unittest.main()
