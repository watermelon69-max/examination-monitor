# Intelligent Examination Hall Monitoring and Anomaly Detection Agent

An AI-based examination monitoring system that analyzes classroom CCTV/video and automatically identifies suspicious or abnormal activities during university examinations.

## Features

### Core Functionality
- ✅ **Person Detection** - Detect students using YOLOv8
- ✅ **Multi-Object Tracking** - Track students across frames with persistent IDs
- ✅ **Seat Association** - Map students to assigned seats
- ✅ **Event Detection** - Detect 5 types of suspicious activities:
  - Student leaving assigned seat
  - Repeated turning toward another student
  - Mobile phone detection
  - Multiple students gathering
  - Unusual movement
- ✅ **Model-Based Agent** - State machine (NORMAL → OBSERVE → SUSPICIOUS → ALERT) with memory
- ✅ **Rule-Based Reasoning** - Configurable rules for suspicion detection
- ✅ **Temporal Reasoning** - Repeated actions increase risk level over time
- ✅ **Risk Scoring** - Based on confidence, duration, frequency, and event type
- ✅ **Explainable Alerts** - Clear reasoning for each alert
- ✅ **Event Logging** - All events stored with timestamp, student/seat ID, evidence frames
- ✅ **Interactive Dashboard** - Real-time monitoring with visual indicators

## Tech Stack

- **Backend**: Python 3.10+, FastAPI, OpenCV, Ultralytics YOLO, supervision
- **Computer Vision**: YOLOv8, ByteTrack, MediaPipe
- **Frontend**: HTML5, TailwindCSS, Vanilla JavaScript
- **Database**: SQLite with SQLAlchemy
- **Real-time**: WebSockets

## Installation

### Prerequisites
- Python 3.10 or higher
- pip
- Webcam or video file for testing

### Setup

1. **Navigate to project directory**
```bash
cd examination-monitor
```

2. **Create virtual environment**
```bash
python -m venv venv
# Windows
venv\Scripts\activate
# Linux/Mac
source venv/bin/activate
```

3. **Install dependencies**
```bash
pip install -r backend/requirements.txt
```

4. **Download YOLO model** (will auto-download on first run, or manually)
```bash
# Place yolov8n.pt in models/ directory
```

5. **Add test video** (optional)
```bash
# Place your exam video in data/videos/sample.mp4
```

## Usage

### Start the Dashboard
```bash
python run.py
```

Open browser and go to `http://localhost:8000`

### Configure Seats (First Time)
1. Load a video
2. Click "Configure Seats"
3. Click on video to mark seat positions
4. Save configuration

### Start Monitoring
1. Load exam video
2. Ensure seats are configured
3. Click "Start Monitoring"
4. Monitor real-time alerts on dashboard

## Configuration

Edit `config/settings.yaml` to adjust:
- Detection thresholds
- Event detection parameters
- Agent state machine thresholds
- Risk scoring weights
- Evidence storage settings

## Project Structure

```
examination-monitor/
├── backend/          # FastAPI backend and CV pipeline
├── frontend/         # Dashboard UI
├── models/           # YOLO model weights
├── data/             # Videos, evidence frames, database
├── config/           # Configuration files
└── run.py            # Entry point
```

## How It Works

1. **Input**: Video feed from CCTV/exam hall camera
2. **Detection**: YOLO detects all persons in frame
3. **Tracking**: ByteTrack maintains consistent IDs across frames
4. **Association**: Each student linked to nearest assigned seat
5. **Event Detection**: 5 modules analyze behavior
6. **Agent Processing**: Model-based agent with memory and state machine
7. **Risk Assessment**: Rule-based reasoning with temporal accumulation
8. **Alerting**: Explainable alerts with evidence saved
9. **Visualization**: Real-time dashboard updates

## Alert States

- **NORMAL** (Green) - No suspicious activity
- **OBSERVE** (Yellow) - Minor anomalies detected
- **SUSPICIOUS** (Orange) - Multiple/concerning patterns
- **ALERT** (Red) - High risk, requires immediate attention

## Future Enhancements

- [ ] Head pose estimation with MediaPipe for better gaze detection
- [ ] Facial recognition for student identification
- [ ] Integration with exam management system
- [ ] Mobile app for invigilators
- [ ] Advanced analytics and reports
- [ ] GPU acceleration support

## License

This project is for educational purposes.
