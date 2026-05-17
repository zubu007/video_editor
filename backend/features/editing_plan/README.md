# Editing Plan Generator

An AI-powered system that analyzes podcast video transcripts and generates intelligent editing plans using Large Language Models (LLMs).

## Overview

The Editing Plan Generator uses OpenAI's GPT models to analyze your podcast transcript and automatically suggest editing features for each segment. It provides a JSON output with timestamps and feature suggestions, making it easy to automate video editing workflows.

## Features

The system can suggest the following editing features:

- **cut_filler_words**: Remove filler words (um, ah, uh, er, like, so, you know)
- **zoom**: Add zoom effects to emphasize important content
- **insert_stock_footage**: Suggest B-roll or stock footage for visual concepts
- **text_overlay**: Add text overlays for quotes, statistics, or key points
- **transition**: Add transitions between segments
- **audio_duck**: Lower background music during important speech
- **speed_up**: Increase playback speed for less critical content
- **highlight**: Add visual highlighting (borders, glows, effects)

## Installation

1. Install dependencies:
```bash
uv pip install openai>=1.0.0
```

2. Set your OpenAI API key:
```bash
export OPENAI_API_KEY='your-api-key-here'
```

## Usage

### Basic Usage

```python
from features.transcript.extract import extract_transcript_as_sentences
from features.editing_plan.generator import generate_editing_plan, print_editing_plan

# Extract transcript from video
transcript = extract_transcript_as_sentences("path/to/video.mp4")

# Generate editing plan
editing_plan = generate_editing_plan(transcript)

# Display the plan
print_editing_plan(editing_plan)
```

### Command Line Usage

Generate an editing plan from a video file:

```bash
python examples/generate_editing_plan.py path/to/video.mp4 --output editing_plan.json
```

Options:
- `--model_size`: Whisper model size (tiny, base, small, medium, large)
- `--llm_model`: OpenAI model to use (gpt-4, gpt-3.5-turbo)
- `--output`: Save editing plan to JSON file
- `--context`: Additional context for the AI editor
- `--api_key`: OpenAI API key (or use OPENAI_API_KEY env var)

### Demo

Try the demo with sample data (no video file needed):

```bash
python examples/demo_editing_plan.py
```

## Output Format

The editing plan is returned as a JSON array:

```json
[
  {
    "start": 0.0,
    "end": 4.2,
    "feature": "text_overlay",
    "parameters": {
      "text": "AI Technology Podcast",
      "style": "title"
    },
    "reason": "Opening statement - add title overlay"
  },
  {
    "start": 14.3,
    "end": 19.7,
    "feature": "zoom",
    "parameters": {
      "zoom_level": 1.2
    },
    "reason": "Emphasize key capabilities of neural networks"
  },
  {
    "start": 25.1,
    "end": 31.5,
    "feature": "insert_stock_footage",
    "parameters": {
      "search_query": "neural network visualization"
    },
    "reason": "Visual concept that would benefit from B-roll"
  }
]
```

## Advanced Usage

### Custom Context

Provide additional instructions to guide the AI:

```python
editing_plan = generate_editing_plan(
    transcript=transcript,
    additional_context="This is a technical tutorial. Use more text overlays for definitions."
)
```

### Filter by Feature

Extract only specific features from the plan:

```python
from features.editing_plan.generator import filter_editing_plan_by_feature

# Get only zoom and text overlay suggestions
filtered = filter_editing_plan_by_feature(
    editing_plan,
    ['zoom', 'text_overlay']
)
```

### Merge Multiple Plans

Combine editing plans from different sources:

```python
from features.editing_plan.generator import merge_editing_plans

merged = merge_editing_plans([plan1, plan2, plan3])
```

### Save and Load Plans

```python
from features.editing_plan.generator import save_editing_plan, load_editing_plan

# Save to file
save_editing_plan(editing_plan, 'plan.json')

# Load from file
loaded_plan = load_editing_plan('plan.json')
```

## Testing

Run the test suite:

```bash
# Test editing plan functionality
pytest tests/test_editing_plan.py -v

# Run all tests
pytest -v
```

## Architecture

The system consists of three main components:

1. **Feature Registry** (`features/editing_plan/feature_registry.py`)
   - Defines all available editing features
   - Provides feature descriptions for the LLM
   - Validates feature names

2. **LLM Client** (`features/editing_plan/llm_client.py`)
   - Manages OpenAI API communication
   - Formats prompts and parses responses
   - Validates and cleans LLM outputs

3. **Generator** (`features/editing_plan/generator.py`)
   - High-level interface for editing plan generation
   - Utilities for saving, loading, and manipulating plans

## Configuration

### Using Different Models

```python
# Use GPT-3.5 Turbo (faster, cheaper)
plan = generate_editing_plan(transcript, model="gpt-3.5-turbo")

# Use GPT-4 (more sophisticated, better reasoning)
plan = generate_editing_plan(transcript, model="gpt-4")
```

### Custom API Key

```python
plan = generate_editing_plan(
    transcript,
    api_key="your-api-key-here"
)
```

## Error Handling

The system includes validation to ensure:
- Timestamps are within transcript bounds
- Feature names are valid
- Required parameters are present
- JSON output is properly formatted

Invalid decisions are automatically filtered out during validation.

## Examples

See the `examples/` directory for:
- `generate_editing_plan.py`: Full workflow with video transcription
- `demo_editing_plan.py`: Quick demo with sample data

## Contributing

When adding new features:

1. Add the feature definition to `AVAILABLE_FEATURES` in `feature_registry.py`
2. Include name, description, use_case, and parameters
3. Update tests in `tests/test_editing_plan.py`
4. Update this README

## License

See project LICENSE file.
