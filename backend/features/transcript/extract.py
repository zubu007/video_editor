from faster_whisper import WhisperModel


def extract_transcript_as_segments(video_path: str, model_size: str = "base") -> list:
    """
    Extracts transcript from a video file using faster-whisper.

    Args:
        video_path (str): The path to the video file.
        model_size (str, optional): The size of the whisper model to use.
                                    Defaults to "base".

    Returns:
        list: A list of segments from the transcript.
              Each segment is a dictionary with "start", "end", and "text" keys.
    """
    model = WhisperModel(model_size, device="cpu", compute_type="int8")

    segments, info = model.transcribe(video_path, beam_size=5)

    print(
        "Detected language '%s' with probability %f"
        % (info.language, info.language_probability)
    )

    transcript = []
    for segment in segments:
        transcript.append(
            {"start": segment.start, "end": segment.end, "text": segment.text}
        )
        print("[%.2fs -> %.2fs] %s" % (segment.start, segment.end, segment.text))

    return transcript


def extract_transcript_as_sentences(video_path: str, model_size: str = "base") -> list:
    """
    Extracts transcript from a video file as a list of sentences.

    Args:
        video_path (str): The path to the video file.
        model_size (str, optional): The size of the whisper model to use.
                                    Defaults to "base".

    Returns:
        list: A list of sentences from the transcript.
              Each sentence is a dictionary with "start", "end", and "text" keys.
    """
    model = WhisperModel(model_size, device="cpu", compute_type="int8")

    segments, info = model.transcribe(video_path, beam_size=5, word_timestamps=True)

    print(
        "Detected language '%s' with probability %f"
        % (info.language, info.language_probability)
    )

    sentences = []
    current_sentence = None

    for segment in segments:
        for word in segment.words:
            if current_sentence is None:
                current_sentence = {
                    "start": word.start,
                    "end": word.end,
                    "text": word.word,
                }
            else:
                current_sentence["end"] = word.end
                current_sentence["text"] += word.word

            if word.word.endswith((".", "?", "!")):
                sentences.append(current_sentence)
                current_sentence = None

    if current_sentence is not None:
        sentences.append(current_sentence)

    for sentence in sentences:
        print(
            "[%.2fs -> %.2fs] %s"
            % (sentence["start"], sentence["end"], sentence["text"])
        )

    return sentences


def extract_transcript_as_words(video_path: str, model_size: str = "base") -> list:
    """
    Extracts transcript from a video file as a list of words.

    Args:
        video_path (str): The path to the video file.
        model_size (str, optional): The size of the whisper model to use.
                                    Defaults to "base".

    Returns:
        list: A list of words from the transcript.
              Each word is a dictionary with "start", "end", and "word" keys.
    """
    model = WhisperModel(model_size, device="cpu", compute_type="int8")

    segments, info = model.transcribe(video_path, beam_size=5, word_timestamps=True)

    print(
        "Detected language '%s' with probability %f"
        % (info.language, info.language_probability)
    )

    words = []
    for segment in segments:
        for word in segment.words:
            words.append({"start": word.start, "end": word.end, "word": word.word})

    return words
