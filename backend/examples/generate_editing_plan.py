"""
Example script demonstrating how to use the editing plan generator.
"""

import argparse
import os

from backend.features.transcript.extract import extract_transcript_as_sentences
from backend.features.editing_plan.generator import (
    generate_editing_plan,
    print_editing_plan,
    save_editing_plan,
)


def main():
    parser = argparse.ArgumentParser(
        description="Generate an AI-powered editing plan for a podcast video."
    )
    parser.add_argument("video_path", help="Path to the video file")
    parser.add_argument(
        "--model_size",
        default="base",
        help="Whisper model size for transcription (tiny, base, small, medium, large). Default: base",
    )
    parser.add_argument(
        "--llm_model",
        default="llama-3.3-70b-versatile",
        help="Groq model to use. Default: llama-3.3-70b-versatile",
    )
    parser.add_argument(
        "--output", help="Output file path for the editing plan JSON (optional)"
    )
    parser.add_argument(
        "--context",
        default="",
        help="Additional context or instructions for the AI editor",
    )
    parser.add_argument(
        "--api_key",
        help="Groq API key (alternatively set the API_KEY environment variable)",
    )

    args = parser.parse_args()

    # Check for API key
    api_key = args.api_key or os.getenv("API_KEY")
    if not api_key:
        print(
            "Error: Groq API key required. Set API_KEY environment variable or use --api_key"
        )
        return 1

    print(f"Processing video: {args.video_path}")
    print(f"Whisper model: {args.model_size}")
    print(f"LLM model: {args.llm_model}")
    print()

    # Step 1: Extract transcript
    print("Step 1: Extracting transcript from video...")
    transcript = extract_transcript_as_sentences(args.video_path, args.model_size)
    print(f"Extracted {len(transcript)} sentences\n")

    # Step 2: Generate editing plan
    print("Step 2: Generating editing plan using AI...")
    editing_plan = generate_editing_plan(
        transcript=transcript,
        api_key=api_key,
        model=args.llm_model,
        additional_context=args.context,
    )
    print(f"Generated {len(editing_plan)} editing decisions\n")

    # Step 3: Display the plan
    print_editing_plan(editing_plan)

    # Step 4: Save to file if requested
    if args.output:
        save_editing_plan(editing_plan, args.output)

    print("\nDone! The editing plan is ready to be executed.")

    return 0


if __name__ == "__main__":
    exit(main())
