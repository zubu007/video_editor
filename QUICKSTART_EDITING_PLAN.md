# Quick Start Guide - LLM Editing Plan Generator

## Installation

```bash
# Install OpenAI dependency
uv pip install openai>=1.0.0

# Set API key
export OPENAI_API_KEY='your-api-key-here'
```

## Quick Test (No Video Required)

```bash
# Run the demo with sample data
python examples/demo_editing_plan.py
```

## Basic Usage

### Option 1: Python API

```python
from features.transcript.extract import extract_transcript_as_sentences
from features.editing_plan.generator import generate_editing_plan, print_editing_plan

# Extract transcript
transcript = extract_transcript_as_sentences("video.mp4")

# Generate editing plan
plan = generate_editing_plan(transcript)

# Display results
print_editing_plan(plan)
```

### Option 2: Command Line

```bash
# Generate plan from video
python examples/generate_editing_plan.py video.mp4

# Save to file
python examples/generate_editing_plan.py video.mp4 --output plan.json

# Use GPT-3.5 (faster/cheaper)
python examples/generate_editing_plan.py video.mp4 --llm_model gpt-3.5-turbo
```

## What You Get

A JSON array with editing decisions:

```json
[
  {
    "start": 0.0,
    "end": 4.2,
    "feature": "text_overlay",
    "parameters": {"text": "Welcome", "style": "title"},
    "reason": "Opening - add title"
  },
  {
    "start": 8.5,
    "end": 14.3,
    "feature": "zoom",
    "parameters": {"zoom_level": 1.2},
    "reason": "Emphasize key point"
  }
]
```

## Available Features

1. **cut_filler_words** - Remove um, ah, uh, etc.
2. **zoom** - Emphasize important moments
3. **insert_stock_footage** - Add B-roll suggestions
4. **text_overlay** - Add text for quotes/stats
5. **transition** - Smooth scene transitions
6. **audio_duck** - Lower background music
7. **speed_up** - Speed up less important parts
8. **highlight** - Visual emphasis effects

## Testing

```bash
# Run tests
pytest tests/test_editing_plan.py -v
```

## Troubleshooting

**Error: "OpenAI API key required"**
```bash
export OPENAI_API_KEY='your-key'
```

**Error: "Import openai could not be resolved"**
```bash
uv pip install openai
```

**Want to use different model?**
```python
plan = generate_editing_plan(transcript, model="gpt-3.5-turbo")
```

## Next Steps

1. Run `python examples/demo_editing_plan.py` to see it in action
2. Read `features/editing_plan/README.md` for detailed documentation
3. Check out example scripts in `examples/` directory
