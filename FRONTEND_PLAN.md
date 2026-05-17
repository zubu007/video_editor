# Frontend Video Player Implementation Plan

## Table of Contents
1. [Architecture Overview](#architecture-overview)
2. [Technology Stack](#technology-stack)
3. [Phase 1: Foundation (MVP)](#phase-1-foundation-mvp)
4. [Phase 2: Advanced Controls](#phase-2-advanced-controls)
5. [Phase 3: Editor Features](#phase-3-editor-features)
6. [Backend Integration](#backend-integration)
7. [Component Structure](#component-structure)

---

## Architecture Overview

### Project Structure
```
frontend/
├── src/
│   ├── components/
│   │   ├── VideoPlayer/
│   │   │   ├── VideoPlayer.jsx          # Main player component
│   │   │   ├── VideoControls.jsx        # Control bar (play, seek, etc.)
│   │   │   ├── Timeline.jsx             # Timeline with marker support
│   │   │   ├── PlaybackButton.jsx       # Play/pause button
│   │   │   ├── VolumeControl.jsx        # Volume slider
│   │   │   ├── TimeDisplay.jsx          # Current time / duration
│   │   │   ├── FullscreenButton.jsx     # Fullscreen toggle
│   │   │   ├── ProgressBar.jsx          # Seekable progress bar
│   │   │   └── VideoPlayer.css          # Styles
│   │   ├── Upload/
│   │   │   ├── VideoUpload.jsx          # File upload component
│   │   │   └── VideoUpload.css
│   │   └── App.jsx                      # Main app component
│   ├── hooks/
│   │   ├── useVideoPlayer.js            # Custom hook for player logic
│   │   ├── useVideoUpload.js            # Custom hook for upload logic
│   │   └── useKeyboardControls.js       # Keyboard shortcuts
│   ├── utils/
│   │   ├── timeFormat.js                # Time formatting utilities
│   │   └── videoUtils.js                # Video helper functions
│   └── services/
│       └── api.js                       # API calls to FastAPI backend
```

### Core Component Architecture

```
┌─────────────────────────────────────┐
│  VideoPlayer Container              │
│  ┌───────────────────────────────┐  │
│  │  <video> element              │  │
│  │  (controlled via ref)         │  │
│  └───────────────────────────────┘  │
│  ┌───────────────────────────────┐  │
│  │  VideoControls                │  │
│  │  ├─ PlaybackButton            │  │
│  │  ├─ ProgressBar/Timeline      │  │
│  │  ├─ TimeDisplay               │  │
│  │  ├─ VolumeControl             │  │
│  │  └─ FullscreenButton          │  │
│  └───────────────────────────────┘  │
└─────────────────────────────────────┘
```

---

## Technology Stack

### Core
- **React 18** - Latest features (concurrent rendering, automatic batching)
- **Vite** - Fast build tool, better DX than Create React App
- **JavaScript** - Simple and fast (TypeScript optional for future)

### Styling
- **CSS Modules** - Scoped styles, no conflicts

### HTTP Client
- **Axios** - Easy to use, interceptors for auth

### Optional (Phase 3)
- **wavesurfer.js** - For waveform visualization
- **framer-motion** - Smooth animations for UI

---

## Phase 1: Foundation (MVP)

**Timeline: 2-3 days**

### 1.1 Project Setup
- [x] Create planning document
- [ ] Initialize React app with Vite
- [ ] Set up project structure (components, hooks, utils, services)
- [ ] Install dependencies (axios)
- [ ] Configure environment variables for backend URL
- [ ] Test connection to FastAPI backend

### 1.2 Basic Video Element
**Goal:** Display and control video playback

**Components to Create:**
- `VideoPlayer.jsx` - Main container with `<video>` element
- Use `useRef` for video element control
- Basic state management for playback

**State to Track:**
- `isPlaying` - Boolean
- `currentTime` - Number (seconds)
- `duration` - Number (seconds)
- `volume` - Number (0-1)
- `isMuted` - Boolean

**Video Events to Handle:**
- `loadedmetadata` - Video loaded, duration available
- `timeupdate` - Current time changed
- `play` - Video started playing
- `pause` - Video paused
- `ended` - Video finished
- `volumechange` - Volume changed

### 1.3 File Upload - Dual Approach
**Goal:** Support both client-side preview and backend upload

**Client-side Preview:**
- Drag & drop or file input
- Create blob URL from File object: `URL.createObjectURL(file)`
- Immediate preview without upload
- Clean up blob URL on unmount

**Backend Integration:**
- Upload file to FastAPI backend
- Backend returns video URL for playback
- Switch from blob URL to backend URL after upload

**Components to Create:**
- `VideoUpload.jsx` - File upload interface
- `useVideoUpload.js` - Custom hook for upload logic

### 1.4 Basic Controls
**Goal:** Essential playback controls

**Components to Create:**
- `PlaybackButton.jsx` - Play/pause toggle
- `ProgressBar.jsx` - Seekable progress indicator
- `TimeDisplay.jsx` - Current time / total duration
- `VolumeControl.jsx` - Volume slider with mute
- `FullscreenButton.jsx` - Fullscreen toggle
- `VideoControls.jsx` - Container for all controls

**Features:**
- Play/pause button with icon toggle
- Progress bar that updates during playback
- Seekable progress bar (click/drag to seek)
- Time display (e.g., "1:23 / 5:45")
- Volume slider (0-100%)
- Mute/unmute button
- Fullscreen toggle

### 1.5 Backend Endpoints
**New endpoints needed in FastAPI:**

```python
# Upload video
POST /api/video/upload
Request: multipart/form-data (video file)
Response: {
    "file_id": "abc123",
    "file_url": "/api/video/abc123",
    "duration": 125.5,
    "size": 10485760,
    "filename": "video.mp4"
}

# Serve video file
GET /api/video/{file_id}
Response: Video file with streaming support (Range headers)

# List uploaded videos (optional)
GET /api/videos
Response: {
    "videos": [
        {
            "file_id": "abc123",
            "filename": "video.mp4",
            "uploaded_at": "2026-02-26T10:00:00Z",
            "duration": 125.5
        }
    ]
}
```

### 1.6 CORS Configuration
**Backend setup required:**

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # Vite dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

---

## Phase 2: Advanced Controls & Interaction

**Timeline: 2-3 days**

### 2.1 Custom Hook: `useVideoPlayer`
**Goal:** Encapsulate all video player logic in reusable hook

**Responsibilities:**
- Video element ref management
- State management (playing, time, duration, volume, etc.)
- Event listener setup/cleanup
- Playback control functions
- Makes components cleaner and logic reusable

**Hook API:**
```javascript
const {
    videoRef,
    state: { isPlaying, currentTime, duration, volume, isMuted },
    controls: { play, pause, togglePlay, seek, setVolume, toggleMute, toggleFullscreen }
} = useVideoPlayer();
```

### 2.2 Enhanced Timeline
**Goal:** Better user experience for seeking

**Features:**
- Clickable/draggable seek bar
- Hover preview (show time on hover)
- Loading/buffering indicator
- Smooth progress updates (throttled)
- Visual feedback during seeking
- Foundation for markers (Phase 3)

### 2.3 Keyboard Shortcuts
**Goal:** Professional keyboard navigation

**Components to Create:**
- `useKeyboardControls.js` - Custom hook for shortcuts

**Shortcuts:**
- `Space` - Play/Pause
- `Arrow Left` - Seek backward 5 seconds
- `Arrow Right` - Seek forward 5 seconds
- `Arrow Up` - Volume up 10%
- `Arrow Down` - Volume down 10%
- `F` - Fullscreen toggle
- `M` - Mute toggle
- `0-9` - Jump to 0%-90% of video

### 2.4 UI/UX Enhancements
**Features:**
- Loading spinner during buffering
- Error messages for failed uploads/playback
- Responsive design (mobile support)
- Hover effects on controls
- Smooth animations
- Accessibility (ARIA labels, keyboard focus)

---

## Phase 3: Editor-Specific Features (Future)

**Timeline: TBD**

### 3.1 Timeline Markers
**Goal:** Visual representation of editing points

**Features:**
- Display filler word positions from backend
- Show editing points visually on timeline
- Click marker to jump to position
- Color-coded marker types (filler words, cuts, effects)
- Marker tooltips (show word/description)

**Data Structure:**
```javascript
markers = [
    {
        time: 10.5,
        type: 'filler_word',
        label: 'um',
        color: '#ff0000'
    },
    {
        time: 25.3,
        type: 'cut',
        label: 'Remove section',
        color: '#ffaa00'
    }
]
```

### 3.2 Frame-by-frame Stepping
**Goal:** Precise navigation for accurate editing

**Features:**
- Comma (`,`) - Previous frame
- Period (`.`) - Next frame
- Calculate frame rate from video metadata
- Precise seeking using `currentTime`
- Display current frame number

**Implementation:**
```javascript
// Assuming 30 fps
const frameDuration = 1 / 30;
videoRef.current.currentTime += frameDuration; // Next frame
videoRef.current.currentTime -= frameDuration; // Previous frame
```

### 3.3 Waveform Visualization
**Goal:** Audio visualization for easier editing

**Features:**
- Use Web Audio API or wavesurfer.js
- Visual representation of audio amplitude
- Sync waveform with video timeline
- Easier to identify speech patterns, silence, filler words
- Clickable waveform for seeking

### 3.4 Multi-video Preview
**Goal:** Compare original vs edited video

**Features:**
- Side-by-side comparison
- Sync playback between videos
- Toggle between views
- A/B comparison controls

### 3.5 Transcript Integration
**Goal:** Show transcript alongside video

**Features:**
- Display transcript with timestamps
- Highlight current word/sentence during playback
- Click transcript to seek to position
- Edit transcript inline
- Show filler words in different color

### 3.6 Editing Plan Visualization
**Goal:** Show AI-generated editing suggestions

**Features:**
- Display editing plan on timeline
- Preview suggested cuts/effects
- Accept/reject suggestions
- Apply edits to video

---

## Backend Integration

### Video Upload Flow

```
User Action                    Frontend                    Backend
─────────────────────────────────────────────────────────────────
Select file      →   Create blob URL
                     Show preview immediately
                     
Click "Upload"   →   FormData with video    →   Save to disk
                                            →   Generate file_id
                                            →   Store metadata
                                            →   Return file_id & URL
                     
                ←    Receive response       ←
                     
                     Switch video source to backend URL
                     Store file_id for future operations
```

### Video Streaming

**Backend Requirements:**
- Support HTTP Range requests for seeking
- Proper Content-Type headers
- Stream video data (don't load entire file)

**Frontend:**
- Video element automatically handles streaming
- Range requests sent when seeking

### Processing Integration

**Workflow:**
1. User uploads video → Get file_id
2. User requests transcript → POST `/api/transcript/words` with file_id
3. Backend processes, returns transcript
4. User requests filler word removal → POST `/api/video/cut-filler-words`
5. Backend returns edited video
6. Frontend displays edited video

---

## Component Structure Details

### VideoPlayer Component

**Props:**
```javascript
{
    src: string,              // Video URL or blob URL
    markers?: Marker[],       // Timeline markers (Phase 3)
    onTimeUpdate?: (time) => void,
    onEnded?: () => void,
    autoPlay?: boolean,
    controls?: boolean,       // Show custom controls
}
```

**State (via useVideoPlayer hook):**
```javascript
{
    isPlaying: boolean,
    currentTime: number,
    duration: number,
    volume: number,
    isMuted: boolean,
    isFullscreen: boolean,
    buffering: boolean,
    error: string | null,
}
```

### VideoUpload Component

**Props:**
```javascript
{
    onVideoSelect: (file: File, blobUrl: string) => void,
    onUploadComplete: (response) => void,
    accept?: string,          // File types (default: "video/*")
    maxSize?: number,         // Max file size in bytes
}
```

**Features:**
- Drag and drop zone
- File input button
- File validation (type, size)
- Upload progress indicator
- Error handling

---

## State Management Strategy

### Phase 1 & 2: Component State
- Use `useState` and `useReducer` in custom hooks
- Simple, no external dependencies
- Easy to understand and maintain

### Phase 3: Context API (if needed)
- If multiple components need player state
- Useful when adding multi-video features
- VideoPlayerContext for shared state

### Future: Zustand/Redux (optional)
- Only if app grows significantly
- Better dev tools and debugging
- Not recommended for initial implementation

---

## Video Event Handling Strategy

### Essential Events

```javascript
// 1. Metadata loaded - Set duration, enable controls
video.addEventListener('loadedmetadata', () => {
    setDuration(video.duration);
    setReady(true);
});

// 2. Time update - Update progress (throttled for performance)
video.addEventListener('timeupdate', () => {
    setCurrentTime(video.currentTime);
});

// 3. Play/Pause - Update UI state
video.addEventListener('play', () => setIsPlaying(true));
video.addEventListener('pause', () => setIsPlaying(false));

// 4. Ended - Reset or show replay
video.addEventListener('ended', () => {
    setIsPlaying(false);
    onEnded?.();
});

// 5. Volume change - Sync volume UI
video.addEventListener('volumechange', () => {
    setVolume(video.volume);
    setIsMuted(video.muted);
});

// 6. Seeking/Seeked - Show loading indicator
video.addEventListener('seeking', () => setBuffering(true));
video.addEventListener('seeked', () => setBuffering(false));

// 7. Waiting - Show buffering spinner
video.addEventListener('waiting', () => setBuffering(true));
video.addEventListener('canplay', () => setBuffering(false));

// 8. Error - Display error message
video.addEventListener('error', (e) => {
    setError('Failed to load video');
});
```

### Performance Optimization

**Throttling timeupdate:**
- `timeupdate` fires frequently (~4 times per second)
- Throttle updates to 60fps max
- Use `requestAnimationFrame` for smooth updates

```javascript
let rafId = null;
video.addEventListener('timeupdate', () => {
    if (!rafId) {
        rafId = requestAnimationFrame(() => {
            setCurrentTime(video.currentTime);
            rafId = null;
        });
    }
});
```

---

## File Upload Best Practices

### Client-side Preview
```javascript
const handleFileSelect = (file) => {
    // Validate file
    if (!file.type.startsWith('video/')) {
        setError('Please select a video file');
        return;
    }
    
    // Create blob URL
    const blobUrl = URL.createObjectURL(file);
    setVideoSrc(blobUrl);
    
    // Clean up on unmount
    return () => URL.revokeObjectURL(blobUrl);
};
```

### Backend Upload
```javascript
const uploadVideo = async (file) => {
    const formData = new FormData();
    formData.append('video', file);
    
    try {
        const response = await axios.post('/api/video/upload', formData, {
            headers: { 'Content-Type': 'multipart/form-data' },
            onUploadProgress: (progressEvent) => {
                const percentCompleted = Math.round(
                    (progressEvent.loaded * 100) / progressEvent.total
                );
                setUploadProgress(percentCompleted);
            }
        });
        
        return response.data;
    } catch (error) {
        console.error('Upload failed:', error);
        throw error;
    }
};
```

---

## Styling Strategy

### CSS Modules Approach

**Benefits:**
- Scoped styles (no conflicts)
- Simple, no runtime overhead
- Works great with Vite
- Easy to understand

**File structure:**
```
VideoPlayer.jsx
VideoPlayer.module.css
```

**Usage:**
```javascript
import styles from './VideoPlayer.module.css';

<div className={styles.videoPlayer}>
    <video className={styles.video} />
    <div className={styles.controls} />
</div>
```

### Design Principles

**1. Clean, Modern Interface**
- Minimal chrome when not in use
- Show controls on hover
- Smooth transitions
- High contrast for readability

**2. Responsive Design**
- Mobile-first approach
- Touch-friendly controls
- Adaptive layout

**3. Accessibility**
- Keyboard navigation
- ARIA labels
- Focus indicators
- Screen reader support

---

## Testing Strategy

### Phase 1 & 2
- Manual testing in browser
- Test in multiple browsers (Chrome, Firefox, Safari)
- Test with different video formats (mp4, webm)
- Test with different video sizes

### Phase 3
- Unit tests for utilities (timeFormat, etc.)
- Component tests with React Testing Library
- E2E tests with Playwright/Cypress

---

## Development Milestones

### Milestone 1: Basic Player (Week 1)
- ✅ Project setup
- ✅ Video player component
- ✅ File upload (client-side)
- ✅ Basic controls (play, pause, seek)

### Milestone 2: Full Controls (Week 2)
- Volume control
- Fullscreen
- Time display
- Better UI/styling
- Backend upload integration

### Milestone 3: Enhanced UX (Week 3)
- Keyboard shortcuts
- Custom hook refactoring
- Loading states
- Error handling
- Responsive design

### Milestone 4: Editor Integration (Future)
- Timeline markers
- Transcript display
- Editing plan visualization
- Frame-by-frame stepping

---

## Resources & References

### Documentation
- [MDN: HTMLMediaElement](https://developer.mozilla.org/en-US/docs/Web/API/HTMLMediaElement)
- [MDN: Media Events](https://developer.mozilla.org/en-US/docs/Web/Guide/Events/Media_events)
- [React Documentation](https://react.dev/)
- [Vite Documentation](https://vitejs.dev/)

### Inspiration
- YouTube player
- Vimeo player
- Video.js player
- Plyr player

---

## Notes

- Build with solid foundation for future editor features
- Keep components small and focused
- Prioritize performance (large video files)
- Mobile support from the start
- Accessibility is important
