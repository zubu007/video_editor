# Video Editor Backend API

A FastAPI-based REST API for automated video editing operations including transcript extraction, filler word removal, editing plan generation, and stock footage integration.

## Features

- **Transcript Extraction**: Extract transcripts from videos at segment, sentence, or word level using Whisper AI
- **Filler Word Detection**: Automatically detect filler words (um, ah, uh, er, like, so, you know)
- **Video Cutting**: Remove filler words from videos automatically
- **AI Editing Plans**: Generate intelligent editing suggestions using GPT-4
- **Stock Footage**: Download stock footage from Pexels API

## Installation

1. Install dependencies:
```bash
uv pip install -e .
```

2. Set up environment variables (create a `.env` file):
```
OPENAI_API_KEY=your_openai_api_key_here
PEXELS_API_KEY=your_pexels_api_key_here
```

## Running the Server

Start the FastAPI server:

```bash
uvicorn backend.app:app --reload --host 0.0.0.0 --port 8000
```

The API will be available at `http://localhost:8000`

## API Documentation

Once the server is running, visit:
- **Interactive API docs (Swagger UI)**: http://localhost:8000/docs
- **Alternative API docs (ReDoc)**: http://localhost:8000/redoc

## API Endpoints

### Transcript Extraction

#### Extract Transcript as Segments
```
POST /api/transcript/segments
```
Upload a video file and get transcript divided into logical segments.

**Parameters:**
- `video` (file): Video file to transcribe
- `model_size` (string, optional): Whisper model size (tiny, base, small, medium, large). Default: "base"

**Response:**
```json
{
  "language": "en",
  "segments": [
    {
      "start": 0.0,
      "end": 5.2,
      "text": "Welcome to this podcast about AI."
    }
  ]
}
```

#### Extract Transcript as Sentences
```
POST /api/transcript/sentences
```
Upload a video file and get transcript divided into sentences.

#### Extract Transcript as Words
```
POST /api/transcript/words
```
Upload a video file and get word-level transcript with precise timestamps.

**Response:**
```json
{
  "language": "en",
  "words": [
    {
      "start": 0.0,
      "end": 0.5,
      "word": "Welcome "
    }
  ]
}
```

### Filler Word Operations

#### Detect Filler Words
```
POST /api/filler-words/detect
```
Analyze a video and detect filler words with their timestamps.

**Response:**
```json
{
  "filler_word_ranges": [
    {
      "start": 2.3,
      "end": 2.6
    }
  ],
  "count": 15
}
```

#### Remove Filler Words
```
POST /api/video/cut-filler-words
```
Automatically remove filler words from a video and download the edited version.

**Parameters:**
- `video` (file): Video file to edit
- `model_size` (string, optional): Whisper model size. Default: "base"

**Response:** Returns edited video file as download

### Editing Plan

#### Generate AI Editing Plan
```
POST /api/editing-plan/generate
```
Generate intelligent editing suggestions using AI analysis of the video content.

**Parameters:**
- `video` (file): Video file to analyze
- `model_size` (string, optional): Whisper model size. Default: "base"
- `api_key` (string, optional): OpenAI API key (uses env var if not provided)
- `llm_model` (string, optional): LLM model to use. Default: "gpt-4"
- `additional_context` (string, optional): Additional instructions for editing

**Response:**
```json
{
  "editing_plan": [
    {
      "start": 0.0,
      "end": 3.5,
      "feature": "text_overlay",
      "parameters": {
        "text": "AI Podcast",
        "style": "title"
      },
      "reason": "Opening statement - add title overlay"
    }
  ]
}
```

### Stock Footage

#### Download Stock Footage
```
POST /api/stock-footage/download
```
Download stock footage from Pexels based on search term.

**Parameters:**
- `search_term` (string): Search query (e.g., "ocean waves")
- `quality` (string, optional): Video quality (hd, sd, or original). Default: "hd"

**Response:**
```json
{
  "file_path": "temp/outputs/pexels_ocean_waves_12345.mp4",
  "search_term": "ocean waves"
}
```

#### Get Stock Footage File
```
GET /api/stock-footage/download/{filename}
```
Download a previously fetched stock footage file.

### Health Check

#### Root
```
GET /
```
API information and available endpoints.

#### Health Check
```
GET /health
```
Health status of the API.

## Example Usage with cURL

### Extract Transcript
```bash
curl -X POST "http://localhost:8000/api/transcript/sentences" \
  -F "video=@/path/to/video.mp4" \
  -F "model_size=base"
```

### Detect Filler Words
```bash
curl -X POST "http://localhost:8000/api/filler-words/detect" \
  -F "video=@/path/to/video.mp4" \
  -F "model_size=base"
```

### Remove Filler Words
```bash
curl -X POST "http://localhost:8000/api/video/cut-filler-words" \
  -F "video=@/path/to/video.mp4" \
  -F "model_size=base" \
  --output edited_video.mp4
```

### Generate Editing Plan
```bash
curl -X POST "http://localhost:8000/api/editing-plan/generate" \
  -F "video=@/path/to/video.mp4" \
  -F "model_size=base" \
  -F "additional_context=This is a tech podcast"
```

### Download Stock Footage
```bash
curl -X POST "http://localhost:8000/api/stock-footage/download" \
  -F "search_term=ocean waves" \
  -F "quality=hd"
```

## Frontend Integration

All endpoints are designed to be easily integrated with frontend buttons and forms. Each endpoint:
- Accepts multipart/form-data for file uploads
- Returns JSON responses (except file download endpoints)
- Includes proper error handling with HTTP status codes
- Supports CORS (can be configured in app.py)

Example frontend integration with JavaScript:

```javascript
// Upload video and get transcript
async function extractTranscript(videoFile) {
  const formData = new FormData();
  formData.append('video', videoFile);
  formData.append('model_size', 'base');
  
  const response = await fetch('http://localhost:8000/api/transcript/sentences', {
    method: 'POST',
    body: formData
  });
  
  return await response.json();
}

// Remove filler words
async function removeFiller(videoFile) {
  const formData = new FormData();
  formData.append('video', videoFile);
  
  const response = await fetch('http://localhost:8000/api/video/cut-filler-words', {
    method: 'POST',
    body: formData
  });
  
  const blob = await response.blob();
  return URL.createObjectURL(blob);
}
```

## Project Structure

```
backend/
├── app.py                 # Main FastAPI application
├── features/              # Feature modules
│   ├── transcript/        # Transcript extraction
│   ├── filler_words/      # Filler word detection
│   ├── video_cutter/      # Video cutting operations
│   ├── editing_plan/      # AI editing plan generation
│   └── pexels/           # Stock footage integration
├── utils/                 # Utility functions
├── tests/                 # Test files
├── examples/              # Example scripts
└── main.py               # CLI entry point (legacy)

temp/
├── uploads/              # Temporary uploaded files
└── outputs/              # Processed output files
```

## Development

### Adding CORS Support

To enable CORS for frontend access, add to `backend/app.py`:

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### Running Tests

```bash
pytest backend/tests/
```

## Notes

- Temporary files are automatically cleaned up after processing
- The server creates `temp/uploads` and `temp/outputs` directories on startup
- Larger videos and higher quality models will take longer to process
- Ensure you have sufficient disk space for video processing
