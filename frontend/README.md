# Video Editor Frontend

A React-based video player with upload functionality, built with Vite.

## Features

- **Video Upload**: Drag & drop or browse to select video files
- **Client-side Preview**: Instant preview using blob URLs (no upload required)
- **Custom Video Player**: 
  - Play/pause controls
  - Seekable progress bar with hover preview
  - Volume control with mute
  - Fullscreen support
  - Time display (current / total)
  - Auto-hiding controls
  - Buffering indicator
- **Responsive Design**: Works on desktop and mobile
- **Backend Integration**: Ready to connect with FastAPI backend for advanced features

## Quick Start

### 1. Install Dependencies

```bash
cd frontend
npm install
```

### 2. Configure Environment

The `.env` file is already configured to connect to the backend at `http://localhost:8000`.

If you need to change it:
```
VITE_API_BASE_URL=http://localhost:8000
```

### 3. Start Development Server

```bash
npm run dev
```

The app will be available at `http://localhost:5173`

### 4. Start Backend (Optional)

If you want to test backend integration:

```bash
# From the project root
python run_server.py
```

## Development

### Project Structure

```
frontend/
├── src/
│   ├── components/
│   │   ├── VideoPlayer/       # Video player component and controls
│   │   │   ├── VideoPlayer.jsx
│   │   │   ├── VideoControls.jsx
│   │   │   ├── PlaybackButton.jsx
│   │   │   ├── ProgressBar.jsx
│   │   │   ├── TimeDisplay.jsx
│   │   │   ├── VolumeControl.jsx
│   │   │   ├── FullscreenButton.jsx
│   │   │   └── *.module.css
│   │   └── Upload/
│   │       ├── VideoUpload.jsx
│   │       └── VideoUpload.module.css
│   ├── hooks/                 # Custom React hooks (future)
│   ├── utils/                 # Utility functions
│   │   ├── timeFormat.js
│   │   └── videoUtils.js
│   ├── services/              # API client
│   │   └── api.js
│   ├── App.jsx
│   ├── App.css
│   └── main.jsx
└── package.json
```

### Available Scripts

```bash
# Start dev server
npm run dev

# Build for production
npm run build

# Preview production build
npm run preview

# Lint code
npm run lint
```

## Usage

### Basic Usage

1. Open the app in your browser
2. Drag & drop a video file or click "Browse Files"
3. The video will instantly load in the player
4. Use the controls to play, pause, seek, adjust volume, and go fullscreen

### Keyboard Shortcuts (Coming in Phase 2)

- `Space` - Play/Pause
- `Arrow Left` - Seek backward 5 seconds
- `Arrow Right` - Seek forward 5 seconds
- `Arrow Up` - Volume up 10%
- `Arrow Down` - Volume down 10%
- `F` - Toggle fullscreen
- `M` - Toggle mute

## Component API

### VideoPlayer

```jsx
<VideoPlayer
  src={videoUrl}              // Video URL (blob or http)
  onTimeUpdate={(time) => {}} // Called when playback time updates
  onEnded={() => {}}          // Called when video ends
  autoPlay={false}            // Auto-play on load
/>
```

### VideoUpload

```jsx
<VideoUpload
  onVideoSelect={(file, blobUrl) => {}}  // Called when file is selected
  onUploadProgress={(percent) => {}}      // Upload progress (future)
/>
```

## Styling

The app uses CSS Modules for component-specific styling:
- Scoped styles (no conflicts)
- Modern, clean design
- Smooth animations and transitions
- Responsive layout

## Browser Support

- Chrome/Edge (latest)
- Firefox (latest)
- Safari (latest)
- Mobile browsers (iOS Safari, Chrome Mobile)

## Future Enhancements (Phase 2 & 3)

See [FRONTEND_PLAN.md](../FRONTEND_PLAN.md) for detailed roadmap:

- **Phase 2**: Custom hooks, keyboard shortcuts, enhanced UI/UX
- **Phase 3**: Timeline markers, transcript integration, frame-by-frame stepping, waveform visualization

## Contributing

Follow the guidelines in [AGENTS.md](../AGENTS.md) for code style and development workflow.

