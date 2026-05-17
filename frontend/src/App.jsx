import { useState, useRef } from 'react';
import VideoPlayer from './components/VideoPlayer/VideoPlayer';
import VideoUpload from './components/Upload/VideoUpload';
import TranscriptPanel from './components/TranscriptPanel/TranscriptPanel';
import { uploadVideo, getVideoURL, getWaveformData, extractWords } from './services/api';
import './App.css';

function App() {
  const [videoSrc, setVideoSrc] = useState(null);
  const [selectedFile, setSelectedFile] = useState(null);
  const [fileId, setFileId] = useState(null);
  const [waveformData, setWaveformData] = useState(null);
  const [transcriptWords, setTranscriptWords] = useState([]);
  const [currentTime, setCurrentTime] = useState(0);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [isUploading, setIsUploading] = useState(false);
  const [isLoadingWaveform, setIsLoadingWaveform] = useState(false);
  const [isLoadingTranscript, setIsLoadingTranscript] = useState(false);
  const videoPlayerRef = useRef(null);

  const handleVideoSelect = async (file, blobUrl) => {
    // Clean up previous blob URL
    if (videoSrc && videoSrc.startsWith('blob:')) {
      URL.revokeObjectURL(videoSrc);
    }

    setSelectedFile(file);
    setVideoSrc(blobUrl);
    setWaveformData(null);
    setTranscriptWords([]);
    setIsUploading(true);
    setUploadProgress(0);

    try {
      // Upload video to backend
      console.log('Uploading video to backend...');
      const response = await uploadVideo(file, (progress) => {
        setUploadProgress(progress);
      });

      console.log('Video uploaded:', response);
      setFileId(response.file_id);

      // Fetch waveform data and transcript in parallel
      console.log('Fetching waveform data and transcript...');
      setIsLoadingWaveform(true);
      setIsLoadingTranscript(true);
      
      const [waveform, transcript] = await Promise.all([
        getWaveformData(response.file_id, 2000),
        extractWords(response.file_id, 'base')
      ]);
      
      console.log('Waveform data received:', waveform);
      console.log('Transcript received:', transcript);
      
      setWaveformData(waveform.waveform);
      setTranscriptWords(transcript.words || []);

    } catch (error) {
      console.error('Error uploading video or fetching data:', error);
      // Still allow playback with blob URL even if upload/waveform/transcript fails
    } finally {
      setIsUploading(false);
      setIsLoadingWaveform(false);
      setIsLoadingTranscript(false);
    }
  };

  const handleTimeUpdate = (currentTime) => {
    setCurrentTime(currentTime);
  };

  const handleVideoEnded = () => {
    console.log('Video ended');
  };

  const handleSeek = (time) => {
    if (videoPlayerRef.current) {
      videoPlayerRef.current.seek(time);
    }
  };

  return (
    <div className="app">
      <header className="app-header">
        <h1>Video Editor</h1>
        <p>Upload and preview your video files</p>
      </header>

      <main className="app-main">
        {!videoSrc ? (
          <VideoUpload onVideoSelect={handleVideoSelect} />
        ) : (
          <div className="workspace">
            <div className="player-section">
              <VideoPlayer
                ref={videoPlayerRef}
                src={videoSrc}
                onTimeUpdate={handleTimeUpdate}
                onEnded={handleVideoEnded}
                waveformData={waveformData}
              />
              
              <div className="video-info">
                <h3>Selected Video</h3>
                <p className="file-name">{selectedFile?.name}</p>
                
                {isUploading && (
                  <p className="upload-status">
                    Uploading: {uploadProgress}%
                  </p>
                )}
                
                {isLoadingWaveform && (
                  <p className="upload-status">
                    Generating waveform...
                  </p>
                )}

                {isLoadingTranscript && (
                  <p className="upload-status">
                    Extracting transcript...
                  </p>
                )}
                
                <button
                  className="change-video-btn"
                  onClick={() => {
                    URL.revokeObjectURL(videoSrc);
                    setVideoSrc(null);
                    setSelectedFile(null);
                    setFileId(null);
                    setWaveformData(null);
                    setTranscriptWords([]);
                  }}
                >
                  Change Video
                </button>
              </div>
            </div>
            
            <div className="transcript-section">
              <TranscriptPanel
                words={transcriptWords}
                currentTime={currentTime}
                onSeek={handleSeek}
                loading={isLoadingTranscript}
              />
            </div>
          </div>
        )}
      </main>

      <footer className="app-footer">
        <p>Built with React + Vite</p>
      </footer>
    </div>
  );
}

export default App;
