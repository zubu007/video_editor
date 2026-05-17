# Audio Pause Detection

Detect and analyze audio pauses/silence in video files. This feature extracts audio from videos and identifies segments of silence that exceed a specified duration, useful for automated video editing.

## Overview

The audio pause detection system:
1. Extracts audio from video files as WAV
2. Analyzes the audio waveform for silence
3. Returns timestamps of silence segments
4. Provides utilities for filtering and merging pauses

## Installation

The required dependencies are already in `pyproject.toml`:

```bash
pip install pydub numpy
```

**Note:** This feature requires `ffmpeg` to be installed on your system:
- **macOS**: `brew install ffmpeg`
- **Ubuntu/Debian**: `apt-get install ffmpeg`
- **Windows**: Download from [ffmpeg.org](https://ffmpeg.org/download.html)

## Usage

### Basic Usage

```python
from features.audio_pause.detect import detect_audio_pauses

# Detect pauses of 1+ seconds
pauses = detect_audio_pauses("video.mp4", min_silence_duration=1.0)

for pause in pauses:
    print(f"Silence: {pause['start']:.2f}s - {pause['end']:.2f}s ({pause['duration']:.2f}s)")
```

### Command Line

```bash
# Detect pauses >= 1 second
python examples/detect_pauses.py video.mp4

# Detect pauses >= 2 seconds with custom threshold
python examples/detect_pauses.py video.mp4 --min-duration 2.0 --threshold -35

# Save results to JSON
python examples/detect_pauses.py video.mp4 --output pauses.json

# Filter results
python examples/detect_pauses.py video.mp4 --filter-min 1.5 --filter-max 5.0

# Merge nearby pauses
python examples/detect_pauses.py video.mp4 --merge-gap 0.5
```

## API Reference

### `detect_audio_pauses(video_path, min_silence_duration=1.0, silence_threshold=-40, seek_step=1)`

Detects audio pauses in a video file.

**Parameters:**
- `video_path` (str): Path to video file
- `min_silence_duration` (float): Minimum silence duration in seconds (default: 1.0)
- `silence_threshold` (int): Audio level threshold in dBFS (default: -40)
  - Lower values = stricter detection (e.g., -50 for near-complete silence)
  - Higher values = looser detection (e.g., -30 for quiet but not silent)
- `seek_step` (int): Scanning step size in milliseconds (default: 1)

**Returns:**
```python
[
  {
    "start": 12.5,      # Start time in seconds
    "end": 15.2,        # End time in seconds
    "duration": 2.7     # Duration in seconds
  },
  ...
]
```

### `detect_audio_pauses_from_wav(wav_path, ...)`

Same as above but works directly with WAV files.

### `extract_audio_from_video(video_path, output_path=None)`

Extracts audio from video and saves as WAV.

**Parameters:**
- `video_path` (str): Path to video file
- `output_path` (str, optional): Where to save WAV file (auto-generated if not provided)

**Returns:**
- `str`: Path to the extracted WAV file

### Utility Functions

#### `filter_pauses_by_duration(pauses, min_duration=None, max_duration=None)`

Filter pauses by duration range.

```python
from features.audio_pause.detect import filter_pauses_by_duration

# Only pauses between 1.5 and 5 seconds
filtered = filter_pauses_by_duration(pauses, min_duration=1.5, max_duration=5.0)
```

#### `merge_nearby_pauses(pauses, max_gap=0.5)`

Merge pause segments that are close together.

```python
from features.audio_pause.detect import merge_nearby_pauses

# Merge pauses within 0.5s of each other
merged = merge_nearby_pauses(pauses, max_gap=0.5)
```

#### `get_total_silence_duration(pauses)`

Calculate total duration of all silence.

```python
from features.audio_pause.detect import get_total_silence_duration

total = get_total_silence_duration(pauses)
print(f"Total silence: {total:.2f}s")
```

## Examples

### Example 1: Basic Detection

```python
from features.audio_pause.detect import detect_audio_pauses

pauses = detect_audio_pauses("podcast.mp4", min_silence_duration=2.0)

print(f"Found {len(pauses)} pauses:")
for i, pause in enumerate(pauses, 1):
    print(f"  {i}. {pause['start']:.2f}s - {pause['end']:.2f}s ({pause['duration']:.2f}s)")
```

### Example 2: Find Long Pauses

```python
from features.audio_pause.detect import detect_audio_pauses, filter_pauses_by_duration

# Detect all pauses
pauses = detect_audio_pauses("video.mp4", min_silence_duration=0.5)

# Filter for pauses > 3 seconds
long_pauses = filter_pauses_by_duration(pauses, min_duration=3.0)

print(f"Found {len(long_pauses)} long pauses that should be cut")
```

### Example 3: Extract Audio and Analyze

```python
from features.audio_pause.detect import extract_audio_from_video, detect_audio_pauses_from_wav

# Extract audio once
wav_path = extract_audio_from_video("video.mp4", "audio.wav")

# Try different thresholds
for threshold in [-50, -40, -30]:
    pauses = detect_audio_pauses_from_wav(
        wav_path,
        min_silence_duration=1.0,
        silence_threshold=threshold
    )
    print(f"Threshold {threshold}dB: {len(pauses)} pauses detected")
```

### Example 4: Integration with Video Cutting

```python
from features.audio_pause.detect import detect_audio_pauses
from features.video_cutter.cut import cut_filler_words

# Detect long pauses
pauses = detect_audio_pauses("video.mp4", min_silence_duration=3.0)

# Convert to time ranges for cutting
time_ranges = [
    {"start": p['start'], "end": p['end']}
    for p in pauses
]

# Cut out the pauses
cut_filler_words("video.mp4", time_ranges, "output.mp4")
```

## Understanding Silence Threshold

The `silence_threshold` parameter is measured in dBFS (decibels relative to full scale):

- **-50 dBFS**: Very strict - only detects near-complete silence
- **-40 dBFS** (default): Balanced - detects quiet segments
- **-30 dBFS**: Loose - detects relatively quiet moments
- **-20 dBFS**: Very loose - may detect normal speech pauses

Adjust based on your audio quality and background noise.

## Performance Considerations

- **seek_step**: Smaller values (1ms) are more precise but slower. For faster processing, use 10-100ms.
- **Temporary files**: Audio is extracted to a temporary WAV file and cleaned up automatically
- **Large files**: Processing time scales with video duration

## Testing

Run the test suite:

```bash
PYTHONPATH=. pytest tests/test_audio_pause.py -v
```

The tests create synthetic audio with known silence segments to verify detection accuracy.

## Output Format

All functions return pause data in this format:

```python
[
  {
    "start": 12.5,      # float: start time in seconds
    "end": 15.2,        # float: end time in seconds
    "duration": 2.7     # float: duration in seconds
  }
]
```

This format is compatible with the video cutting features and can be easily serialized to JSON.

## Common Use Cases

1. **Remove long pauses**: Detect and cut pauses > 2 seconds
2. **Find dead air**: Identify segments with no audio activity
3. **Analyze pacing**: Calculate total silence to understand video pacing
4. **Smart editing**: Combine with transcript analysis for intelligent cuts

## Troubleshooting

**"ffmpeg not found"**
- Install ffmpeg on your system (see Installation section)

**"No pauses detected"**
- Try increasing the `silence_threshold` (e.g., -30 instead of -40)
- Decrease `min_silence_duration` (e.g., 0.5 instead of 1.0)
- Check that your video has audio

**"Too many pauses detected"**
- Decrease the `silence_threshold` (e.g., -50 instead of -40)
- Increase `min_silence_duration`
- Use `merge_nearby_pauses()` to consolidate results

## License

See project LICENSE file.
