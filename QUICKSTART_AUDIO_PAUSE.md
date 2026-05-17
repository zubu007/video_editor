# Audio Pause Detection - Quick Start

Detect audio silence/pauses in videos for automated editing.

## Installation

```bash
pip install pydub numpy
```

Make sure `ffmpeg` is installed:
- macOS: `brew install ffmpeg`
- Ubuntu: `apt-get install ffmpeg`

## Quick Usage

### Python API

```python
from features.audio_pause.detect import detect_audio_pauses

# Detect pauses >= 1 second
pauses = detect_audio_pauses("video.mp4", min_silence_duration=1.0)

for pause in pauses:
    print(f"{pause['start']:.2f}s - {pause['end']:.2f}s ({pause['duration']:.2f}s)")
```

### Command Line

```bash
# Basic usage
python examples/detect_pauses.py video.mp4

# Detect pauses >= 2 seconds
python examples/detect_pauses.py video.mp4 --min-duration 2.0

# Save to JSON
python examples/detect_pauses.py video.mp4 --output pauses.json

# Filter and merge
python examples/detect_pauses.py video.mp4 --filter-min 1.5 --merge-gap 0.5
```

## Output Format

```python
[
  {
    "start": 12.5,      # Start time in seconds
    "end": 15.2,        # End time in seconds  
    "duration": 2.7     # Duration in seconds
  }
]
```

## Key Parameters

- **min_silence_duration**: Minimum pause length to detect (seconds)
- **silence_threshold**: Audio level in dBFS (default: -40)
  - `-50` = very strict (near silence only)
  - `-40` = balanced (default)
  - `-30` = loose (quieter moments)

## Utility Functions

```python
from features.audio_pause.detect import (
    filter_pauses_by_duration,
    merge_nearby_pauses,
    get_total_silence_duration
)

# Filter by duration
long_pauses = filter_pauses_by_duration(pauses, min_duration=2.0)

# Merge nearby pauses
merged = merge_nearby_pauses(pauses, max_gap=0.5)

# Get total silence time
total = get_total_silence_duration(pauses)
```

## Testing

```bash
PYTHONPATH=. pytest tests/test_audio_pause.py -v
```

All 10 tests pass ✅

## Integration Example

```python
from features.audio_pause.detect import detect_audio_pauses
from features.video_cutter.cut import cut_filler_words

# Detect long pauses
pauses = detect_audio_pauses("video.mp4", min_silence_duration=3.0)

# Convert to cutting format
cuts = [{"start": p['start'], "end": p['end']} for p in pauses]

# Remove the pauses from video
cut_filler_words("video.mp4", cuts, "output.mp4")
```

## Full Documentation

See `features/audio_pause/README.md` for complete documentation.
