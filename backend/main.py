import argparse
from features.transcript.extract import extract_transcript_as_sentences

def main():
    parser = argparse.ArgumentParser(description="Extract transcript from a video file.")
    parser.add_argument("video_path", help="The path to the video file.")
    parser.add_argument("--model_size", default="base", help="The size of the whisper model to use.")
    args = parser.parse_args()

    transcript = extract_transcript_as_sentences(args.video_path, args.model_size)
    print(transcript)

if __name__ == "__main__":
    main()
