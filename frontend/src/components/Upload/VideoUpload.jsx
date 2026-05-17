import React, { useState, useRef } from 'react';
import { isVideoFile, formatFileSize, createBlobURL, revokeBlobURL } from '../../utils/videoUtils';
import styles from './VideoUpload.module.css';

function VideoUpload({ onVideoSelect, onUploadProgress }) {
  const [isDragging, setIsDragging] = useState(false);
  const [selectedFile, setSelectedFile] = useState(null);
  const [error, setError] = useState(null);
  const fileInputRef = useRef(null);

  const handleFile = (file) => {
    setError(null);

    // Validate file type
    if (!isVideoFile(file)) {
      setError('Please select a valid video file');
      return;
    }

    // Validate file size (max 500MB for client-side preview)
    const maxSize = 500 * 1024 * 1024; // 500MB
    if (file.size > maxSize) {
      setError('File size exceeds 500MB limit');
      return;
    }

    // Create blob URL for preview
    const blobUrl = createBlobURL(file);
    
    setSelectedFile(file);
    onVideoSelect(file, blobUrl);
  };

  const handleFileInputChange = (e) => {
    const file = e.target.files?.[0];
    if (file) {
      handleFile(file);
    }
  };

  const handleDragEnter = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(true);
  };

  const handleDragLeave = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
  };

  const handleDragOver = (e) => {
    e.preventDefault();
    e.stopPropagation();
  };

  const handleDrop = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);

    const file = e.dataTransfer.files?.[0];
    if (file) {
      handleFile(file);
    }
  };

  const handleBrowseClick = () => {
    fileInputRef.current?.click();
  };

  return (
    <div className={styles.uploadContainer}>
      <div
        className={`${styles.dropZone} ${isDragging ? styles.dragging : ''}`}
        onDragEnter={handleDragEnter}
        onDragLeave={handleDragLeave}
        onDragOver={handleDragOver}
        onDrop={handleDrop}
      >
        <input
          ref={fileInputRef}
          type="file"
          accept="video/*"
          onChange={handleFileInputChange}
          className={styles.fileInput}
        />

        <div className={styles.dropZoneContent}>
          <svg width="64" height="64" viewBox="0 0 24 24" fill="currentColor" className={styles.uploadIcon}>
            <path d="M9 16h6v-6h4l-7-7-7 7h4zm-4 2h14v2H5z"/>
          </svg>

          <h3 className={styles.title}>Drop video file here</h3>
          <p className={styles.subtitle}>or</p>
          
          <button onClick={handleBrowseClick} className={styles.browseButton}>
            Browse Files
          </button>

          <p className={styles.hint}>Supported formats: MP4, WebM, MOV (max 500MB)</p>
        </div>

        {selectedFile && (
          <div className={styles.selectedFile}>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
              <path d="M9 16.2L4.8 12l-1.4 1.4L9 19 21 7l-1.4-1.4L9 16.2z"/>
            </svg>
            <span className={styles.fileName}>{selectedFile.name}</span>
            <span className={styles.fileSize}>({formatFileSize(selectedFile.size)})</span>
          </div>
        )}
      </div>

      {error && (
        <div className={styles.error}>
          <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
            <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z"/>
          </svg>
          <span>{error}</span>
        </div>
      )}
    </div>
  );
}

export default VideoUpload;
