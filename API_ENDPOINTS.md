# API Endpoint Summary

Quick reference for all available API endpoints.

## Base URL
`http://localhost:8000`

## Available Endpoints

### 1. Transcript Extraction

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/transcript/segments` | POST | Extract transcript as segments |
| `/api/transcript/sentences` | POST | Extract transcript as sentences |
| `/api/transcript/words` | POST | Extract word-level transcript |

**Common Parameters:**
- `video` (file, required): Video file to transcribe
- `model_size` (string, optional): Whisper model size (tiny/base/small/medium/large)

### 2. Filler Word Operations

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/filler-words/detect` | POST | Detect filler words in video |
| `/api/video/cut-filler-words` | POST | Remove filler words from video |

**Common Parameters:**
- `video` (file, required): Video file to process
- `model_size` (string, optional): Whisper model size

### 3. AI Editing Plan

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/editing-plan/generate` | POST | Generate AI editing suggestions |

**Parameters:**
- `video` (file, required): Video file to analyze
- `model_size` (string, optional): Whisper model size
- `api_key` (string, optional): OpenAI API key
- `llm_model` (string, optional): LLM model (default: gpt-4)
- `additional_context` (string, optional): Extra instructions

### 4. Stock Footage

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/stock-footage/download` | POST | Download stock footage from Pexels |
| `/api/stock-footage/download/{filename}` | GET | Get downloaded stock footage file |

**Parameters (POST):**
- `search_term` (string, required): Search query
- `quality` (string, optional): Video quality (hd/sd/original)

### 5. Utility Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | API info and available endpoints |
| `/health` | GET | Health check |
| `/docs` | GET | Interactive API documentation (Swagger UI) |
| `/redoc` | GET | Alternative API documentation (ReDoc) |

## Example Workflow: Remove Filler Words

1. **Upload video** → `/api/video/cut-filler-words`
2. **Receive edited video** → Download the result

Single API call handles everything!

## Example Workflow: Complete Editing

1. **Extract transcript** → `/api/transcript/sentences`
2. **Generate editing plan** → `/api/editing-plan/generate`
3. **Download stock footage** → `/api/stock-footage/download` (if needed)
4. **Remove filler words** → `/api/video/cut-filler-words`

Each endpoint can be connected to a frontend button for easy access!
