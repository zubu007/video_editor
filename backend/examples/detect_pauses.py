"""
Example script for detecting audio pauses in video files.
"""

import argparse
import json

from backend.features.audio_pause.detect import (
    detect_audio_pauses,
    filter_pauses_by_duration,
    get_total_silence_duration,
    merge_nearby_pauses,
)


def format_time(seconds: float) -> str:
    """
    Formats seconds as MM:SS.mmm

    Args:
        seconds (float): Time in seconds.

    Returns:
        str: Formatted time string.
    """
    minutes = int(seconds // 60)
    secs = seconds % 60
    return f"{minutes:02d}:{secs:06.3f}"


def main():
    parser = argparse.ArgumentParser(
        description="Detect audio pauses/silence in video files."
    )
    parser.add_argument("video_path", help="Path to the video file")
    parser.add_argument(
        "--min-duration",
        type=float,
        default=1.0,
        help="Minimum silence duration in seconds to detect (default: 1.0)",
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=-40,
        help="Silence threshold in dBFS (default: -40). Lower = stricter",
    )
    parser.add_argument(
        "--filter-min",
        type=float,
        help="Filter results to only show pauses >= this duration",
    )
    parser.add_argument(
        "--filter-max",
        type=float,
        help="Filter results to only show pauses <= this duration",
    )
    parser.add_argument(
        "--merge-gap",
        type=float,
        help="Merge pauses that are within this many seconds of each other",
    )
    parser.add_argument("--output", help="Save results to JSON file")
    parser.add_argument("--verbose", action="store_true", help="Show detailed output")

    args = parser.parse_args()

    print(f"Analyzing video: {args.video_path}")
    print(f"Min silence duration: {args.min_duration}s")
    print(f"Silence threshold: {args.threshold} dBFS")
    print()

    # Detect pauses
    print("Detecting audio pauses...")
    pauses = detect_audio_pauses(
        args.video_path,
        min_silence_duration=args.min_duration,
        silence_threshold=args.threshold,
    )

    print(f"Found {len(pauses)} pause(s)\n")

    # Apply filters if requested
    if args.filter_min or args.filter_max:
        original_count = len(pauses)
        pauses = filter_pauses_by_duration(
            pauses, min_duration=args.filter_min, max_duration=args.filter_max
        )
        print(
            f"After filtering: {len(pauses)} pause(s) (removed {original_count - len(pauses)})\n"
        )

    # Merge nearby pauses if requested
    if args.merge_gap:
        original_count = len(pauses)
        pauses = merge_nearby_pauses(pauses, max_gap=args.merge_gap)
        print(
            f"After merging: {len(pauses)} pause(s) (merged {original_count - len(pauses)})\n"
        )

    # Display results
    if pauses:
        print("=" * 80)
        print("DETECTED PAUSES")
        print("=" * 80)

        for i, pause in enumerate(pauses, 1):
            print(f"\nPause {i}:")
            print(f"  Start:    {format_time(pause['start'])} ({pause['start']:.3f}s)")
            print(f"  End:      {format_time(pause['end'])} ({pause['end']:.3f}s)")
            print(f"  Duration: {pause['duration']:.3f}s")

        print()
        print("=" * 80)
        total_silence = get_total_silence_duration(pauses)
        print(f"Total silence: {total_silence:.3f}s ({format_time(total_silence)})")
        print("=" * 80)
    else:
        print("No pauses detected with the current settings.")
        print("Try:")
        print("  - Lowering --min-duration")
        print("  - Increasing --threshold (e.g., -30)")

    # Save to JSON if requested
    if args.output:
        with open(args.output, "w") as f:
            json.dump(pauses, f, indent=2)
        print(f"\nResults saved to: {args.output}")

    # Verbose output
    if args.verbose and pauses:
        print("\nTimestamps for video editing:")
        for pause in pauses:
            print(f"{pause['start']:.3f} - {pause['end']:.3f}")

    return 0


if __name__ == "__main__":
    exit(main())
