# Video Editor - Quick Start Guide

## Windows Dota 2 setup

Install Git for Windows, uv, and Node.js 20.19+ (20.x) or 22.12+, then run from
PowerShell:

```powershell
git clone https://github.com/zubu007/video_editor.git
cd video_editor
powershell -ExecutionPolicy Bypass -File scripts/setup-windows.ps1
powershell -ExecutionPolicy Bypass -File scripts/start-windows.ps1
```

Open <http://127.0.0.1:5173>, choose **Edit a gaming video**, and upload the full
gameplay recording. In **Deaths**, choose the team, load the hero portraits,
select your hero, and run **Detect deaths**. Review the intervals, select **Add
cuts**, then use **Render / Export** to create and download the edited MP4.

Death cutting needs no API keys and no OCR installation. The detector reads the
golden respawn timer under the selected top-bar hero and ends each cut on normal
respawn, buyback, or Aegis return. It requires a visible standard Dota HUD and
the correct team and hero selection.

## Phase 1 Complete! ✅

You now have a fully functional web-based video player with upload capabilities.

## What's Been Built

### Frontend (React + Vite)
- ✅ Custom video player with HTML5 video element
- ✅ Drag & drop file upload
- ✅ Client-side instant preview (blob URLs)
- ✅ Complete playback controls:
  - Play/Pause button
  - Seekable progress bar with hover preview
  - Time display (current/total)
  - Volume control with mute
  - Fullscreen support
  - Auto-hiding controls
  - Buffering indicators
- ✅ Modern, responsive UI
- ✅ Error handling

### Backend (FastAPI)
- ✅ CORS configuration for frontend
- ✅ Video upload endpoint (`POST /api/video/upload`)
- ✅ Video serving endpoint with streaming (`GET /api/video/{file_id}`)
- ✅ All existing features still work (transcript, filler words, etc.)

## How to Run

### 1. Start the Backend

```bash
# From project root
python run_server.py
```

Backend will be available at: `http://localhost:8000`

### 2. Start the Frontend

```bash
# In a new terminal
cd frontend
npm run dev
```

Frontend will be available at: `http://localhost:5173`

### 3. Test the Player

1. Open `http://localhost:5173` in your browser
2. Drag and drop a video file (MP4, WebM, MOV, etc.)
3. Watch it instantly load and play!

## Features You Can Use Right Now

### Upload and Play
- **Instant Preview**: No upload required, uses blob URLs
- **Drag & Drop**: Easy file selection
- **File Validation**: Only accepts video files

### Player Controls
- **Click to Play/Pause**: Click anywhere on the video
- **Seek**: Click or drag on the progress bar
- **Volume**: Hover over volume icon to show slider
- **Fullscreen**: Click fullscreen button
- **Time Hover**: Hover over progress bar to see time preview

### Auto-hiding Controls
- Controls appear when you move the mouse
- Automatically hide after 3 seconds of inactivity during playback
- Always visible when paused

## What's Next (Phase 2)

See [FRONTEND_PLAN.md](FRONTEND_PLAN.md) for the complete roadmap.

### Upcoming Features:
1. **Keyboard Shortcuts** - Space, arrows, F, M keys
2. **Custom Hook** - `useVideoPlayer` for better code organization
3. **Enhanced Timeline** - Better seeking UX
4. **Loading States** - Better upload feedback
5. **Error Messages** - User-friendly error handling

### Future (Phase 3):
1. **Timeline Markers** - Show filler words, editing points
2. **Frame-by-frame** - Precise navigation
3. **Transcript Display** - Show transcript alongside video
4. **Waveform** - Audio visualization
5. **Multi-video** - Compare original vs edited

## File Structure

```
video_editor/
├── frontend/                  # React frontend (NEW!)
│   ├── src/
│   │   ├── components/
│   │   │   ├── VideoPlayer/  # Player components
│   │   │   └── Upload/       # Upload component
│   │   ├── utils/            # Utilities
│   │   ├── services/         # API client
│   │   └── App.jsx
│   ├── package.json
│   └── README.md
├── backend/                   # FastAPI backend (UPDATED!)
│   ├── app.py               # Added CORS + upload endpoints
│   ├── features/
│   └── ...
├── temp/
│   └── uploads/             # Uploaded videos stored here
├── FRONTEND_PLAN.md         # Detailed implementation plan
└── QUICKSTART.md            # This file
```

## API Endpoints

### New Endpoints
- `POST /api/video/upload` - Upload video file
- `GET /api/video/{file_id}` - Get video file (streaming)

### Existing Endpoints
- `POST /api/transcript/segments` - Extract transcript
- `POST /api/transcript/words` - Word-level transcript
- `POST /api/filler-words/detect` - Detect filler words
- `POST /api/video/cut-filler-words` - Remove filler words
- `POST /api/editing-plan/generate` - AI editing plan
- `POST /api/stock-footage/download` - Download stock footage

Visit `http://localhost:8000/docs` for interactive API documentation.

## Troubleshooting

### Frontend won't start
```bash
cd frontend
npm ci
npm run dev
```

### Backend errors
```bash
# Make sure you're in the virtual environment
source .venv/bin/activate  # or .venv\Scripts\activate on Windows

# Install dependencies
uv pip install -e .
```

### Video won't play
- Make sure the file is a valid video format (MP4, WebM, MOV)
- Check browser console for errors
- Try a different video file

### CORS errors
- Make sure backend is running on port 8000
- Check that frontend is running on port 5173
- Restart both servers if needed

## Development Tips

### Hot Reload
Both frontend and backend support hot reload:
- Frontend: Edit any file in `frontend/src/` and see changes instantly
- Backend: Edit Python files and uvicorn will auto-reload

### Component Development
- All player controls are separate components
- Use CSS Modules for styling (scoped, no conflicts)
- Components are in `frontend/src/components/`

### Adding Features
1. Create new component in appropriate folder
2. Import and use in parent component
3. Add CSS module for styling
4. Update FRONTEND_PLAN.md with progress

## Resources

- **Frontend Plan**: See [FRONTEND_PLAN.md](FRONTEND_PLAN.md)
- **Backend API**: Visit `http://localhost:8000/docs`
- **Code Style**: See [AGENTS.md](AGENTS.md)
- **Backend README**: See [backend/README.md](backend/README.md)

## Questions?

- Check [FRONTEND_PLAN.md](FRONTEND_PLAN.md) for architecture details
- Look at component files for implementation examples
- Review [AGENTS.md](AGENTS.md) for coding guidelines

---

**Great job!** You've successfully built a custom video player from scratch! 🎉

Next: Implement Phase 2 features (keyboard shortcuts, custom hooks, enhanced UX)
