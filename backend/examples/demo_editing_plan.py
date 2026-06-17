"""
Demo script showing the editing plan generator with sample data.
This doesn't require a video file - it uses a pre-made transcript.
"""

import os

from backend.features.editing_plan.generator import (
    generate_editing_plan,
    print_editing_plan,
)


def main():
    # Sample podcast transcript
    sample_transcript = [
        {"start": 0.0, "end": 4.2, "text": " Welcome to the AI Technology Podcast."},
        {
            "start": 4.2,
            "end": 8.5,
            "text": " Today we are going to discuss the future of neural networks.",
        },
        {
            "start": 8.5,
            "end": 14.3,
            "text": " Neural networks have revolutionized machine learning in the past decade.",
        },
        {
            "start": 14.3,
            "end": 19.7,
            "text": " They can now process images, understand language, and even generate art.",
        },
        {
            "start": 19.7,
            "end": 25.1,
            "text": " But um, you know, there are still challenges we need to overcome.",
        },
        {
            "start": 25.1,
            "end": 31.5,
            "text": " One major challenge is interpretability - understanding how neural networks make decisions.",
        },
        {
            "start": 31.5,
            "end": 36.8,
            "text": " Another challenge is computational efficiency and energy consumption.",
        },
        {
            "start": 36.8,
            "end": 42.0,
            "text": " Looking ahead, I believe we will see more efficient architectures.",
        },
        {
            "start": 42.0,
            "end": 47.5,
            "text": " So that brings us to our key takeaway for today.",
        },
        {
            "start": 47.5,
            "end": 53.2,
            "text": " Neural networks are powerful but we must focus on making them more transparent and efficient.",
        },
    ]

    # Check for API key
    api_key = os.getenv("API_KEY")
    if not api_key:
        print("ERROR: Please set the API_KEY environment variable")
        print("\nExample:")
        print("  export API_KEY='your-groq-api-key-here'")
        print("  python examples/demo_editing_plan.py")
        return 1

    print("=" * 80)
    print("EDITING PLAN DEMO")
    print("=" * 80)
    print("\nThis demo will generate an AI-powered editing plan for a sample podcast.")
    print("The LLM will analyze the transcript and suggest editing features.\n")

    print("Sample Transcript:")
    print("-" * 80)
    for segment in sample_transcript:
        print(f"[{segment['start']:.1f}s - {segment['end']:.1f}s] {segment['text']}")
    print()

    # Generate editing plan
    print("\nGenerating editing plan using Groq...")
    print("(This may take 10-30 seconds)\n")

    try:
        editing_plan = generate_editing_plan(
            transcript=sample_transcript,
            api_key=api_key,
            model="llama-3.3-70b-versatile",
            additional_context="This is a technology podcast. Focus on making it engaging and professional.",
        )

        # Display the plan
        print_editing_plan(editing_plan)

        print(
            "\nSuccess! The AI has analyzed the content and suggested editing features."
        )
        print(
            "Each decision includes timestamps, the feature to use, and the reasoning.\n"
        )

    except Exception as e:
        print(f"\nError generating editing plan: {e}")
        print("\nMake sure you have:")
        print("1. A valid Groq API key")
        print("2. Sufficient API credits")
        print("3. Internet connection")
        return 1

    return 0


if __name__ == "__main__":
    exit(main())
