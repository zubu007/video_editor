import re

FILLER_WORDS = ["um", "ah", "uh", "er", "like", "so", "you know"]

def detect_filler_words(words: list) -> list:
    """
    Detects filler words in a list of words.

    Args:
        words (list): A list of words from the transcript.
                      Each word is a dictionary with "start", "end", and "word" keys.

    Returns:
        list: A list of time ranges for the filler words.
              Each time range is a dictionary with "start" and "end" keys.
    """
    filler_word_ranges = []
    for word in words:
        # Using regex for a case-insensitive match and to handle variations
        if re.search(r'\b(' + '|'.join(FILLER_WORDS) + r')\b', word['word'], re.IGNORECASE):
            filler_word_ranges.append({
                "start": word['start'],
                "end": word['end']
            })
    return filler_word_ranges
