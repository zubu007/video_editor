# ML-Based Filler Word Detection Plan

## Problem Statement

Current filler word detection relies on Whisper transcription, which often cleans up or skips filler words ("um", "uh", "ah", "er") because speech-to-text models are trained to produce clean transcripts. This plan outlines an audio-based machine learning approach to detect filler words directly from the audio signal without relying on transcription.

---

## Overview

Build an audio classification system that directly detects filler words from audio using acoustic features (MFCCs, spectral features) and a machine learning classifier.

**Target Performance**: 85%+ F1-score
**Estimated Total Time**: 21-30 hours
**Priority**: Medium (future enhancement)

---

## Phase 1: Setup Dependencies & Infrastructure

### 1.1 Add Required Libraries

Update `pyproject.toml` with:
```toml
dependencies = [
    # ... existing dependencies ...
    "librosa>=0.10.0",        # Audio feature extraction (MFCCs, spectrograms)
    "scikit-learn>=1.3.0",    # ML classifiers and preprocessing
    "scipy>=1.11.0",          # Signal processing utilities
    "joblib>=1.3.0",          # Model serialization
    "xgboost>=2.0.0",         # Optional: Gradient boosting (if Random Forest insufficient)
]
```

**Installation**:
```bash
uv pip install librosa scikit-learn scipy joblib xgboost
```

### 1.2 Create Module Structure

```
backend/features/filler_words_ml/
├── __init__.py
├── feature_extractor.py    # Extract MFCC, spectral features from audio
├── classifier.py            # Train/predict filler words using ML
├── dataset.py              # Create training dataset and annotation tools
├── trainer.py              # Training pipeline and evaluation
├── models/                 # Directory for saved trained models
│   ├── .gitkeep
│   └── filler_word_rf.pkl  # Random Forest model (example)
├── datasets/               # Training data annotations
│   ├── .gitkeep
│   └── annotations.json    # Labeled filler word timestamps
└── README.md               # Documentation
```

**Estimated Time**: 1-2 hours

---

## Phase 2: Feature Extraction System

### 2.1 Implement Audio Feature Extraction

**File**: `backend/features/filler_words_ml/feature_extractor.py`

#### Key Functions:

**A. MFCC Feature Extraction**
```python
def extract_mfcc_features(audio_segment: np.ndarray, sample_rate: int) -> np.ndarray:
    """
    Extract Mel-Frequency Cepstral Coefficients (MFCCs).
    
    Args:
        audio_segment: Audio data as numpy array
        sample_rate: Sample rate in Hz (typically 22050 or 44100)
    
    Returns:
        Feature vector with shape (39,):
        - 13 MFCC coefficients
        - 13 delta (velocity) coefficients
        - 13 delta-delta (acceleration) coefficients
    
    Implementation:
        - Use librosa.feature.mfcc()
        - n_mfcc=13 (standard for speech)
        - Calculate deltas with librosa.feature.delta()
        - Take mean across time axis for fixed-length vector
    """
```

**B. Spectral Feature Extraction**
```python
def extract_spectral_features(audio_segment: np.ndarray, sample_rate: int) -> np.ndarray:
    """
    Extract spectral characteristics of audio.
    
    Returns feature vector with ~5 features:
    - Spectral centroid (brightness/center of mass of spectrum)
    - Spectral rolloff (frequency below which 85% of energy is contained)
    - Zero-crossing rate (signal sign changes, indicates noisiness)
    - RMS energy (overall loudness)
    - Spectral bandwidth (width of frequency band)
    
    Implementation:
        - Use librosa.feature.spectral_centroid()
        - Use librosa.feature.spectral_rolloff()
        - Use librosa.feature.zero_crossing_rate()
        - Use librosa.feature.rms()
        - Use librosa.feature.spectral_bandwidth()
        - Take mean across time for each feature
    """
```

**C. Combined Feature Extraction**
```python
def extract_combined_features(audio_segment: np.ndarray, sample_rate: int) -> np.ndarray:
    """
    Combines MFCC + spectral features.
    
    Returns:
        Standardized feature vector (44 features):
        - 39 MFCC features
        - 5 spectral features
    
    Notes:
        - Features should be normalized/scaled for ML
        - Use sklearn.preprocessing.StandardScaler during training
    """
```

### 2.2 Sliding Window Detection

```python
def sliding_window_analysis(
    audio_array: np.ndarray,
    sample_rate: int,
    window_ms: int = 300,
    hop_ms: int = 50
) -> list[dict]:
    """
    Scan audio with overlapping windows and extract features.
    
    Args:
        audio_array: Full audio as numpy array
        sample_rate: Audio sample rate
        window_ms: Window size in milliseconds (default: 300ms)
        hop_ms: Hop size between windows (default: 50ms)
    
    Returns:
        List of dictionaries:
        [
            {
                'start': 0.0,      # Start time in seconds
                'end': 0.3,        # End time in seconds
                'features': [...], # Feature vector (44 features)
            },
            ...
        ]
    
    Implementation Notes:
        - 300ms window captures typical filler word duration (100-500ms)
        - 50ms hop ensures we don't miss short filler words
        - Convert ms to samples: samples = int(ms * sample_rate / 1000)
    """
```

**Estimated Time**: 3-4 hours

---

## Phase 3: Dataset Creation & Annotation

### 3.1 Manual Annotation Tool

**File**: `backend/features/filler_words_ml/dataset.py`

#### CLI Annotation Tool

```python
# Usage:
python -m backend.features.filler_words_ml.dataset annotate video.mp4

# Interactive prompts:
# - Play audio segment
# - User marks: [f]iller word, [s]peech, [i]lence, [p]lay again, [n]ext
# - If filler: specify type (um/uh/ah/er)
# - Save annotations to JSON
```

#### Features:
- Play audio segments in a loop
- Keyboard controls for marking segments
- Support for marking:
  - **Filler words** (positive class): um, uh, ah, er
  - **Speech** (negative class): normal words, sentences
  - **Silence** (negative class): pauses, no audio
- Auto-save annotations to JSON file
- Resume annotation from where you left off
- Export segments as WAV files for inspection

### 3.2 Dataset Format

**File**: `backend/features/filler_words_ml/datasets/annotations.json`

```json
{
  "metadata": {
    "version": "1.0",
    "created_at": "2026-03-07T10:30:00Z",
    "total_samples": 500
  },
  "files": [
    {
      "file_path": "temp/uploads/podcast1.mp4",
      "file_id": "abc123",
      "duration": 1200.5,
      "annotations": [
        {
          "start": 12.5,
          "end": 12.8,
          "duration": 0.3,
          "type": "um",
          "label": "filler_word",
          "annotator": "manual",
          "confidence": 1.0
        },
        {
          "start": 30.2,
          "end": 31.1,
          "duration": 0.9,
          "type": "speech",
          "label": "not_filler",
          "annotator": "manual",
          "confidence": 1.0
        },
        {
          "start": 45.0,
          "end": 45.15,
          "duration": 0.15,
          "type": "uh",
          "label": "filler_word",
          "annotator": "manual",
          "confidence": 1.0
        }
      ]
    }
  ]
}
```

### 3.3 Balanced Dataset Generation

**Goals**:
- Extract filler word segments → **positive class**
- Extract random speech segments → **negative class**
- Extract silence segments → **negative class**
- Balance classes: ~33% each or equal samples
- **Target**: 500-1000 total samples for initial training
  - 250-500 filler word samples
  - 250-500 non-filler samples

**Data Augmentation** (optional for improving robustness):
- Time stretching (0.9x to 1.1x speed)
- Pitch shifting (±2 semitones)
- Add background noise (low level)
- Volume variation (±3 dB)

**Estimated Time**: 6-8 hours (includes manual annotation)

---

## Phase 4: Model Training

### 4.1 Classifier Implementation

**File**: `backend/features/filler_words_ml/classifier.py`

```python
class FillerWordClassifier:
    """
    Machine learning classifier for filler word detection.
    """
    
    def __init__(self, model_type: str = 'random_forest'):
        """
        Args:
            model_type: 'random_forest', 'xgboost', 'svm', or 'neural_network'
        """
        self.model_type = model_type
        self.model = None
        self.scaler = StandardScaler()
    
    def train(self, X_train: np.ndarray, y_train: np.ndarray):
        """
        Train the classifier.
        
        Args:
            X_train: Feature matrix (n_samples, 44)
            y_train: Labels (n_samples,) - 1 for filler, 0 for not_filler
        
        Returns:
            Dict with training metrics
        """
        # 1. Normalize features with StandardScaler
        # 2. Train-test split (80/20)
        # 3. Cross-validation (5-fold)
        # 4. Hyperparameter tuning with GridSearchCV
        # 5. Train final model on full training set
        # 6. Evaluate on test set
        # 7. Save model + scaler
    
    def predict(self, features: np.ndarray) -> np.ndarray:
        """
        Predict probability of filler word.
        
        Returns:
            Array of probabilities (0.0 to 1.0)
        """
        # Scale features
        # Return model.predict_proba()
    
    def predict_binary(self, features: np.ndarray, threshold: float = 0.7) -> np.ndarray:
        """
        Returns binary classification (0 or 1).
        """
        probs = self.predict(features)
        return (probs >= threshold).astype(int)
    
    def save(self, filepath: str):
        """Save model and scaler to disk."""
        joblib.dump({
            'model': self.model,
            'scaler': self.scaler,
            'model_type': self.model_type
        }, filepath)
    
    def load(self, filepath: str):
        """Load model and scaler from disk."""
        data = joblib.load(filepath)
        self.model = data['model']
        self.scaler = data['scaler']
        self.model_type = data['model_type']
```

### 4.2 Algorithm Comparison

Try multiple algorithms and compare performance:

#### A. Random Forest (Recommended Starting Point)
```python
from sklearn.ensemble import RandomForestClassifier

model = RandomForestClassifier(
    n_estimators=100,
    max_depth=10,
    min_samples_split=5,
    class_weight='balanced',  # Handle class imbalance
    random_state=42
)
```

**Pros**: Fast training, interpretable, works well with 500+ samples
**Cons**: Can overfit without proper tuning

#### B. XGBoost (If Random Forest Insufficient)
```python
import xgboost as xgb

model = xgb.XGBClassifier(
    n_estimators=100,
    max_depth=6,
    learning_rate=0.1,
    scale_pos_weight=1,  # Adjust for class imbalance
    random_state=42
)
```

**Pros**: Higher accuracy, handles imbalance well
**Cons**: Slower training, more hyperparameters

#### C. SVM with RBF Kernel (Classic for Audio)
```python
from sklearn.svm import SVC

model = SVC(
    kernel='rbf',
    C=1.0,
    gamma='scale',
    probability=True,  # Enable predict_proba
    class_weight='balanced'
)
```

**Pros**: Good for non-linear patterns
**Cons**: Slow on large datasets, sensitive to scaling

#### D. Simple Neural Network (Optional)
```python
from sklearn.neural_network import MLPClassifier

model = MLPClassifier(
    hidden_layer_sizes=(64, 32),
    activation='relu',
    max_iter=500,
    random_state=42
)
```

**Pros**: Can capture complex patterns
**Cons**: Needs more data, harder to tune

### 4.3 Training Pipeline

**File**: `backend/features/filler_words_ml/trainer.py`

```python
def train_filler_word_model(
    annotations_path: str,
    output_model_path: str,
    model_type: str = 'random_forest'
) -> dict:
    """
    Complete training pipeline.
    
    Steps:
    1. Load annotations from JSON
    2. Extract audio segments and features for each annotation
    3. Create feature matrix X and labels y
    4. Train model with cross-validation
    5. Evaluate on test set
    6. Save model to disk
    7. Return evaluation metrics
    
    Returns:
        {
            'accuracy': 0.89,
            'precision': 0.87,
            'recall': 0.91,
            'f1_score': 0.89,
            'confusion_matrix': [[tn, fp], [fn, tp]],
            'roc_auc': 0.93
        }
    """
```

### 4.4 Model Evaluation

**Metrics to Track**:
- **Precision**: Of detected filler words, how many are correct? (minimize false positives)
- **Recall**: Of actual filler words, how many did we detect? (minimize false negatives)
- **F1-Score**: Harmonic mean of precision and recall (primary metric)
- **Confusion Matrix**: True/false positives/negatives
- **ROC Curve & AUC**: Overall discriminative ability

**Target Performance**:
- **F1-Score**: >85%
- **Precision**: >80% (important - don't want to cut real speech)
- **Recall**: >85% (catch most filler words)

**Evaluation Tools**:
```python
from sklearn.metrics import classification_report, confusion_matrix, roc_curve, auc

# Print detailed report
print(classification_report(y_true, y_pred, target_names=['not_filler', 'filler']))

# Plot confusion matrix
sns.heatmap(confusion_matrix(y_true, y_pred), annot=True)

# Plot ROC curve
fpr, tpr, _ = roc_curve(y_true, y_scores)
plt.plot(fpr, tpr, label=f'AUC = {auc(fpr, tpr):.3f}')
```

**Estimated Time**: 4-6 hours

---

## Phase 5: Integration with Video Editor

### 5.1 New Backend Endpoint

**File**: `backend/app.py`

```python
# Add Pydantic model
class FillerWordML(BaseModel):
    """Model for ML-detected filler word."""
    start: float = Field(..., description="Start time in seconds")
    end: float = Field(..., description="End time in seconds")
    type: str = Field(..., description="Filler word type (um/uh/ah/er)")
    confidence: float = Field(..., description="ML confidence score (0.0-1.0)")


class FillerWordsMLResponse(BaseModel):
    """Response model for ML-based filler word detection."""
    filler_words: list[FillerWordML] = []
    count: int = Field(..., description="Number of filler words detected")
    method: str = Field(default="ml_classifier", description="Detection method used")
    processing_time: float = Field(..., description="Processing time in seconds")


@app.get("/api/filler-words/detect-ml/{file_id}", response_model=FillerWordsMLResponse)
async def detect_filler_words_ml(
    file_id: str,
    threshold: float = 0.7,  # Confidence threshold (0.0-1.0)
    window_ms: int = 300,    # Sliding window size in ms
    hop_ms: int = 50,        # Hop size in ms
):
    """
    Detect filler words using ML-based audio classification.
    
    This endpoint uses acoustic features (MFCCs, spectral features) and a
    trained machine learning classifier to detect filler words directly from
    audio without relying on transcription.
    
    Args:
        file_id: Unique file identifier from video upload
        threshold: Confidence threshold for classification (default: 0.7)
        window_ms: Sliding window size in milliseconds (default: 300)
        hop_ms: Hop size between windows in milliseconds (default: 50)
    
    Returns:
        List of detected filler words with timestamps and confidence scores
    """
    import time
    from backend.features.filler_words_ml.detector import detect_filler_words_ml
    
    start_time = time.time()
    
    try:
        # Find video file
        video_path = find_video_by_file_id(file_id, UPLOAD_DIR)
        
        # Run ML detection
        logger.info(f"Running ML-based filler word detection on {file_id}")
        detections = detect_filler_words_ml(
            video_path=str(video_path),
            threshold=threshold,
            window_ms=window_ms,
            hop_ms=hop_ms
        )
        
        processing_time = time.time() - start_time
        
        return FillerWordsMLResponse(
            filler_words=detections,
            count=len(detections),
            method="ml_classifier",
            processing_time=processing_time
        )
    
    except FileNotFoundError as e:
        logger.error(f"File not found: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    
    except Exception as e:
        logger.error(f"Error detecting filler words with ML: {e}")
        raise HTTPException(status_code=500, detail=str(e))
```

### 5.2 Detection Pipeline

**File**: `backend/features/filler_words_ml/detector.py`

```python
def detect_filler_words_ml(
    video_path: str,
    threshold: float = 0.7,
    window_ms: int = 300,
    hop_ms: int = 50,
    model_path: str = "backend/features/filler_words_ml/models/filler_word_rf.pkl"
) -> list[dict]:
    """
    Complete detection pipeline.
    
    Steps:
    1. Load video and extract audio to numpy array
    2. Load trained ML model
    3. Run sliding window analysis
    4. Extract features for each window
    5. Classify each window (filler vs. not_filler)
    6. Post-process detections:
       - Merge adjacent positive windows
       - Filter by confidence threshold
       - Remove very short segments (<100ms)
       - Classify filler type (um/uh/ah/er) if possible
    7. Return time ranges with confidence scores
    
    Returns:
        [
            {
                'start': 12.5,
                'end': 12.8,
                'type': 'um',
                'confidence': 0.92
            },
            ...
        ]
    """
```

**Post-Processing Functions**:

```python
def merge_adjacent_detections(detections: list[dict], max_gap: float = 0.1) -> list[dict]:
    """
    Merge detections that are very close together (likely same filler word).
    
    Args:
        detections: List of detection dicts
        max_gap: Maximum gap in seconds to merge (default: 0.1s)
    """

def filter_short_detections(detections: list[dict], min_duration: float = 0.1) -> list[dict]:
    """
    Remove very short detections that are likely false positives.
    """

def classify_filler_type(audio_segment: np.ndarray, sample_rate: int) -> str:
    """
    Attempt to classify specific filler word type (um/uh/ah/er).
    
    This is optional and more challenging. Could use:
    - Frequency analysis (um vs. uh have different formants)
    - Separate classifier for type classification
    - Simple heuristics based on spectral features
    
    Returns:
        'um', 'uh', 'ah', 'er', or 'unknown'
    """
```

### 5.3 Frontend Integration

#### A. Update API Service

**File**: `frontend/src/services/api.js`

```javascript
/**
 * Detect filler words using ML-based audio classification
 * @param {string} fileId - File ID
 * @param {number} threshold - Confidence threshold (0.0-1.0, default: 0.7)
 * @param {number} windowMs - Sliding window size in ms (default: 300)
 * @param {number} hopMs - Hop size in ms (default: 50)
 * @returns {Promise<{filler_words: Array, count: number, method: string}>}
 */
export async function detectFillerWordsML(fileId, threshold = 0.7, windowMs = 300, hopMs = 50) {
  const response = await apiClient.get(`/api/filler-words/detect-ml/${fileId}`, {
    params: { threshold, window_ms: windowMs, hop_ms: hopMs },
  });

  return response.data;
}
```

#### B. Display on Waveform

**Update**: `frontend/src/components/VideoPlayer/WaveformProgress.jsx`

Add filler word markers:
```javascript
// Props
const { waveformData, currentTime, duration, onSeek, fillerWords } = props;

// In render function
{fillerWords && fillerWords.map((filler, idx) => {
  const x = (filler.start / duration) * canvas.width;
  const width = ((filler.end - filler.start) / duration) * canvas.width;
  
  // Draw orange/red marker for filler word
  ctx.fillStyle = `rgba(255, 87, 34, ${filler.confidence * 0.6})`;
  ctx.fillRect(x, 0, width, canvas.height);
})}
```

Add hover tooltip to show filler word details:
```javascript
const handleMouseMove = (e) => {
  // ... existing code ...
  
  // Check if hovering over filler word
  const hoveredFiller = fillerWords.find(f => 
    time >= f.start && time <= f.end
  );
  
  if (hoveredFiller) {
    setTooltip({
      time,
      text: `Filler: "${hoveredFiller.type}" (${(hoveredFiller.confidence * 100).toFixed(0)}%)`
    });
  }
};
```

#### C. Add Detection Controls

**Update**: `frontend/src/App.jsx`

```javascript
const [detectionMethod, setDetectionMethod] = useState('transcription'); // or 'ml'
const [fillerWords, setFillerWords] = useState([]);

// Add detection button
<select value={detectionMethod} onChange={e => setDetectionMethod(e.target.value)}>
  <option value="transcription">Transcription-based</option>
  <option value="ml">ML Audio-based</option>
  <option value="hybrid">Hybrid (Both)</option>
</select>

<button onClick={handleDetectFillerWords}>
  Detect Filler Words
</button>

const handleDetectFillerWords = async () => {
  if (detectionMethod === 'ml') {
    const result = await detectFillerWordsML(fileId, 0.7);
    setFillerWords(result.filler_words);
  } else if (detectionMethod === 'transcription') {
    // Use existing transcript-based detection
  } else if (detectionMethod === 'hybrid') {
    // Combine both methods
  }
};
```

**Estimated Time**: 3-4 hours

---

## Phase 6: Optimization & Refinement

### 6.1 Hybrid Approach (Recommended)

Combine both methods for best results:

```python
def detect_filler_words_hybrid(video_path: str) -> list[dict]:
    """
    Hybrid detection using both transcription and ML.
    
    Strategy:
    1. Run Whisper transcription (catches words it transcribes)
    2. Run ML classifier (catches words Whisper misses)
    3. Merge results:
       - ML detections take priority for "um/uh/ah/er"
       - Transcription used for "like/so/you know" (harder to detect by audio alone)
    4. Remove duplicates (same timestamp from both methods)
    
    Returns:
        Combined list of filler word detections
    """
```

**Benefits**:
- **Best of both worlds**: ML catches audio patterns, transcription catches semantic fillers
- **Higher recall**: Catch more filler words overall
- **Confidence scoring**: Use both methods to validate detections

### 6.2 Performance Optimization

**A. Feature Caching**
```python
# Cache extracted features for long videos
from functools import lru_cache

@lru_cache(maxsize=100)
def get_cached_features(video_path: str, window_index: int):
    """Cache features to avoid recomputation."""
```

**B. Chunk Processing**
```python
def process_video_in_chunks(video_path: str, chunk_duration: float = 60.0):
    """
    Process long videos in chunks to reduce memory usage.
    
    Process 60-second chunks at a time instead of loading entire audio.
    """
```

**C. Parallel Processing**
```python
from multiprocessing import Pool

def extract_features_parallel(windows: list, num_workers: int = 4):
    """
    Extract features from multiple windows in parallel.
    
    Use multiprocessing.Pool to process windows concurrently.
    """
```

**D. GPU Acceleration (Optional)**
```python
# If user has GPU available
import cupy as cp  # GPU-accelerated NumPy

# Use GPU for FFT operations in librosa
# Requires librosa with GPU support or custom implementation
```

### 6.3 Model Improvement & Active Learning

**A. Collect User Feedback**
```python
# Add endpoint for user corrections
@app.post("/api/filler-words/feedback/{file_id}")
async def submit_filler_word_feedback(
    file_id: str,
    correction: FillerWordCorrection
):
    """
    User can mark false positives/negatives.
    
    Save corrections to database/file for retraining.
    """
```

**B. Incremental Retraining**
```python
def retrain_with_feedback(
    current_model_path: str,
    feedback_annotations_path: str,
    output_model_path: str
):
    """
    Retrain model with user-corrected annotations.
    
    Periodically retrain model with accumulated feedback
    to improve performance over time.
    """
```

**C. Per-User/Video-Type Tuning**
```python
# Allow threshold adjustment per user preference
# Store optimal threshold per video type (podcast, lecture, interview)

user_preferences = {
    'default_threshold': 0.7,
    'video_type_thresholds': {
        'podcast': 0.65,  # More sensitive for podcasts
        'lecture': 0.75,  # Less sensitive for lectures (more formal)
    }
}
```

**Estimated Time**: 4-6 hours

---

## Alternative: Lightweight Heuristic Approach

If the full ML pipeline seems too complex, consider this **simpler approach** first:

### Heuristic-Based Detection (2-4 hours)

**File**: `backend/features/filler_words_ml/heuristic_detector.py`

```python
def detect_filler_words_heuristic(video_path: str) -> list[dict]:
    """
    Rule-based filler word detection without ML training.
    
    Steps:
    1. Extract audio to numpy array
    2. Detect very short low-energy segments (100-300ms)
    3. Analyze frequency spectrum with FFT
    4. Apply heuristic rules:
       - Duration: 0.1s < duration < 0.5s
       - Dominant frequency: 200-400 Hz (typical for um/uh)
       - Low spectral complexity (vs. words like "the", "and")
       - Preceded or followed by pause (>50ms silence)
    5. Return detected segments
    
    Expected Performance: 60-70% F1-score
    """
```

**Heuristic Rules**:
```python
def is_likely_filler_word(segment: np.ndarray, sample_rate: int) -> bool:
    """
    Simple heuristic rules for filler word detection.
    """
    duration = len(segment) / sample_rate
    
    # Rule 1: Duration check (filler words are short)
    if not (0.1 < duration < 0.5):
        return False
    
    # Rule 2: Frequency analysis (um/uh have low dominant frequency)
    fft = np.fft.rfft(segment)
    freqs = np.fft.rfftfreq(len(segment), 1/sample_rate)
    dominant_freq = freqs[np.argmax(np.abs(fft))]
    
    if not (200 < dominant_freq < 400):
        return False
    
    # Rule 3: Low spectral variance (simple sound)
    spectral_variance = np.std(np.abs(fft))
    if spectral_variance > THRESHOLD:
        return False
    
    # Rule 4: Energy/RMS check
    rms = np.sqrt(np.mean(segment**2))
    if rms < LOW_ENERGY_THRESHOLD:
        return False
    
    return True
```

**Pros**:
- Fast to implement (2-4 hours)
- No training data needed
- No ML dependencies
- Explainable/debuggable

**Cons**:
- Lower accuracy (~60-70% F1 vs. 85%+ with ML)
- Requires manual tuning of thresholds
- May miss variations in filler word pronunciation
- More false positives/negatives

**Recommendation**: Try this first as a prototype, then upgrade to ML if accuracy insufficient.

---

## Implementation Checklist

### Phase 1: Setup
- [ ] Add librosa, scikit-learn, scipy, joblib to pyproject.toml
- [ ] Install dependencies with `uv pip install`
- [ ] Create module structure: `backend/features/filler_words_ml/`
- [ ] Create subdirectories: `models/`, `datasets/`
- [ ] Add README.md with documentation

### Phase 2: Feature Extraction
- [ ] Implement `extract_mfcc_features()`
- [ ] Implement `extract_spectral_features()`
- [ ] Implement `extract_combined_features()`
- [ ] Implement `sliding_window_analysis()`
- [ ] Write unit tests for feature extraction
- [ ] Verify feature dimensions and normalization

### Phase 3: Dataset Creation
- [ ] Create annotation tool CLI in `dataset.py`
- [ ] Test annotation tool with sample video
- [ ] Manually annotate 500-1000 samples
- [ ] Save annotations to JSON format
- [ ] Validate dataset balance (filler vs. non-filler)
- [ ] Export sample segments for inspection

### Phase 4: Model Training
- [ ] Implement `FillerWordClassifier` class
- [ ] Create training pipeline in `trainer.py`
- [ ] Train Random Forest model
- [ ] Evaluate with cross-validation
- [ ] Test on held-out validation set
- [ ] Achieve target F1-score >85%
- [ ] Save trained model to `models/`
- [ ] Generate evaluation report

### Phase 5: Integration
- [ ] Create `detector.py` with detection pipeline
- [ ] Implement post-processing functions
- [ ] Add backend endpoint `/api/filler-words/detect-ml/{file_id}`
- [ ] Test endpoint with sample video
- [ ] Update frontend API service
- [ ] Add waveform visualization for detections
- [ ] Add detection method toggle (transcription/ML/hybrid)
- [ ] Test end-to-end flow

### Phase 6: Optimization
- [ ] Implement hybrid detection (transcription + ML)
- [ ] Add feature caching for performance
- [ ] Implement chunk processing for long videos
- [ ] Add parallel processing for feature extraction
- [ ] Create feedback collection endpoint
- [ ] Implement incremental retraining pipeline
- [ ] Tune thresholds per video type

### Optional: Heuristic Alternative
- [ ] Implement `heuristic_detector.py`
- [ ] Test heuristic rules on sample videos
- [ ] Compare performance to ML approach
- [ ] Use as fallback or quick prototype

---

## Testing Strategy

### Unit Tests

```python
# tests/test_filler_words_ml.py

def test_mfcc_extraction():
    """Test MFCC feature extraction."""
    # Create synthetic audio (sine wave)
    # Extract MFCCs
    # Verify shape: (39,)
    # Verify value ranges

def test_spectral_features():
    """Test spectral feature extraction."""
    # Test with different audio types
    # Verify feature dimensions

def test_sliding_window():
    """Test sliding window analysis."""
    # Test window overlap
    # Verify timestamps
    # Test edge cases (short audio)

def test_classifier_prediction():
    """Test classifier prediction."""
    # Load trained model
    # Test with known filler word sample
    # Verify confidence score
```

### Integration Tests

```python
def test_full_detection_pipeline():
    """Test complete detection on sample video."""
    # Use annotated test video
    # Run detection
    # Compare against ground truth annotations
    # Calculate precision, recall, F1

def test_api_endpoint():
    """Test ML detection API endpoint."""
    # Upload test video
    # Call /api/filler-words/detect-ml/{file_id}
    # Verify response format
    # Check detection count
```

### Performance Tests

```python
def test_detection_speed():
    """Test detection speed on various video lengths."""
    # Test 1-minute video
    # Test 10-minute video
    # Test 60-minute video
    # Verify processing time is reasonable
```

---

## Performance Benchmarks

### Target Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| **F1-Score** | >85% | Primary accuracy metric |
| **Precision** | >80% | Minimize false positives |
| **Recall** | >85% | Catch most filler words |
| **Processing Speed** | <1x realtime | 10-min video in <10 minutes |
| **Memory Usage** | <2GB | For 60-minute video |
| **Model Size** | <50MB | Trained model file size |

### Expected Performance by Video Type

| Video Type | Expected F1 | Notes |
|------------|-------------|-------|
| Podcast (clear audio) | 85-90% | Ideal conditions |
| Interview (studio) | 80-85% | Good quality |
| Lecture (room mic) | 75-80% | Background noise |
| Conference talk | 70-75% | Poor audio quality |

---

## Documentation

### README.md Content

Create `backend/features/filler_words_ml/README.md` with:

1. **Overview**: What this module does
2. **Installation**: Dependencies and setup
3. **Quick Start**: Training and detection examples
4. **API Reference**: Function signatures and parameters
5. **Model Performance**: Benchmarks and metrics
6. **Troubleshooting**: Common issues and solutions
7. **Future Improvements**: Planned enhancements

### Code Documentation

- Add docstrings to all functions (Google style)
- Include type hints for all parameters
- Add inline comments for complex logic
- Create Jupyter notebook with examples

---

## Future Enhancements

### Short-term (1-2 months)
- [ ] Support for additional filler word types ("you see", "basically", "actually")
- [ ] Multi-language support (Spanish "este", French "euh")
- [ ] Confidence calibration (better probability estimates)
- [ ] Real-time detection for live audio

### Medium-term (3-6 months)
- [ ] Deep learning model (LSTM/Transformer) for better accuracy
- [ ] Speaker-specific fine-tuning
- [ ] Context-aware detection (consider surrounding speech)
- [ ] Auto-labeling tool using existing model to bootstrap annotations

### Long-term (6-12 months)
- [ ] Pre-trained model on large filler word dataset
- [ ] Model marketplace (upload/download community models)
- [ ] Browser-based detection (TensorFlow.js)
- [ ] Mobile app integration

---

## Resources & References

### Academic Papers
- "Automatic Detection of Filler Words in Speech" (IEEE, 2018)
- "Deep Learning for Audio Signal Processing" (arXiv, 2019)
- "MFCC Feature Extraction for Speech Recognition" (tutorial)

### Libraries Documentation
- [librosa documentation](https://librosa.org/doc/latest/)
- [scikit-learn Random Forest](https://scikit-learn.org/stable/modules/ensemble.html#random-forests)
- [XGBoost documentation](https://xgboost.readthedocs.io/)

### Datasets (for reference)
- Common Voice (Mozilla) - speech datasets
- LibriSpeech - English audiobook corpus
- TIMIT - acoustic-phonetic speech corpus

### Tools
- [Audacity](https://www.audacityteam.org/) - Audio editing for annotation
- [Praat](https://www.fon.hum.uva.nl/praat/) - Phonetic analysis
- [Labelbox](https://labelbox.com/) - Data labeling platform (if scaling annotation)

---

## Questions to Address Before Implementation

1. **Audio Quality Requirements**: What's the minimum audio quality expected? (affects model robustness)

2. **Latency Requirements**: Is real-time detection needed, or batch processing acceptable?

3. **Accuracy vs. Speed Tradeoff**: Prefer faster detection with lower accuracy, or slower with higher accuracy?

4. **False Positive Cost**: Is it worse to incorrectly cut real speech (false positive) or miss filler words (false negative)?

5. **Deployment Environment**: Will this run on server, client, or both? (affects model size/complexity)

6. **User Customization**: Should users be able to adjust sensitivity/threshold, or automatic?

7. **Model Updates**: How often should model be retrained with new data?

8. **Privacy Considerations**: Are there privacy concerns with audio analysis or data collection?

---

## Contact & Support

For questions or issues during implementation:
- Check AGENTS.md for coding guidelines
- Review backend/features/audio_pause/ for similar audio processing examples
- Test with small samples first before processing full videos
- Monitor memory usage for long videos
- Use logging extensively for debugging

---

## Conclusion

This plan provides a comprehensive roadmap for implementing ML-based filler word detection. The full implementation requires significant effort (21-30 hours) but will provide much more accurate detection than transcription-based methods.

**Recommended Approach**:
1. Start with **heuristic detection** (2-4 hours) as a quick prototype
2. If accuracy insufficient, proceed with **full ML pipeline**
3. Once ML model is trained, implement **hybrid approach** for best results

The modular design allows incremental development and testing at each phase.
