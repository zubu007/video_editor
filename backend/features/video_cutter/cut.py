from moviepy import VideoFileClip, concatenate_videoclips
import os

def cut_filler_words(video_path: str, filler_word_ranges: list, output_path: str) -> None:
    """
    Cuts filler words from a video file.

    Args:
        video_path (str): The path to the video file.
        filler_word_ranges (list): A list of time ranges for the filler words.
                                   Each time range is a dictionary with "start" and "end" keys.
        output_path (str): The path to save the edited video file.
    """
    video = VideoFileClip(video_path)
    
    # Calculate the clips to keep
    clips_to_keep = []
    last_end = 0
    for filler in filler_word_ranges:
        if filler['start'] > last_end:
            clips_to_keep.append(video.subclip(last_end, filler['start']))
        last_end = filler['end']

    if last_end < video.duration:
        clips_to_keep.append(video.subclip(last_end, video.duration))

    # Concatenate the clips
    if clips_to_keep:
        final_clip = concatenate_videoclips(clips_to_keep)
        final_clip.write_videofile(output_path, codec="libx264", audio_codec="aac")
    else:
        # If all clips are filler words, create an empty video
        video.subclip(0, 0).write_videofile(output_path, codec="libx264", audio_codec="aac")
