# Video Editor

A simple video editing tool with a FastAPI backend for automated podcast video editing.

## Features

- **Transcript Extraction**: Extract transcripts from videos using Whisper AI
- **Filler Word Removal**: Automatically detect and remove filler words (um, ah, uh, etc.)
- **AI Editing Plans**: Generate intelligent editing suggestions using GPT-4
- **Stock Footage Integration**: Download stock footage from Pexels API
- **REST API**: FastAPI-based backend ready for frontend integration

## Quick Start

### 1. Install Dependencies

```bash
uv pip install -e .
```

### 2. Set Up Environment Variables

Create a `.env` file with your API keys:
```
OPENAI_API_KEY=your_openai_api_key_here
PEXELS_API_KEY=your_pexels_api_key_here
```

### 3. Start the Backend Server

```bash
python run_server.py
```

Or using uvicorn directly:
```bash
uvicorn backend.app:app --reload --host 0.0.0.0 --port 8000
```

The API will be available at `http://localhost:8000`

Visit `http://localhost:8000/docs` for interactive API documentation.

## API Documentation

See [backend/README.md](backend/README.md) for detailed API documentation and usage examples.

## Project Structure

```
.
├── backend/               # Backend API code
│   ├── app.py            # FastAPI application
│   ├── features/         # Feature modules
│   ├── utils/            # Utility functions
│   ├── tests/            # Tests
│   └── examples/         # Example scripts
├── run_server.py         # Server startup script
└── pyproject.toml        # Project dependencies
```

## CLI Usage (Legacy)

The original CLI interface is still available in `backend/main.py`:

```bash
python backend/main.py /path/to/video.mp4 --model_size base
```
