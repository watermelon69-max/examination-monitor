import copy
import logging
import threading
import time
from collections import deque
from pathlib import Path
from uuid import uuid4
import cv2
from app.core.config import config
from app.services.agent import ModelBasedAgent
from app.services.seat_manager import SeatManager
from app.services.tracker import StudentTracker
from app.services.event_detectors import EventDetectorManager
from app.services.event_logger import EventLogger
from app.utils.visualization import Visualizer
from app.services.demo import demo_frame, SEATS


def resize_frame(frame):
    width = config.get('video.resize_width', 1280)
    if frame.shape[1] > width:
        frame = cv2.resize(frame, (width, round(frame.shape[0] * width / frame.shape[1])))
    return frame


class MonitoringService:
    def __init__(self, event_logger=None, detector_factory=None):
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.thread = None
        self.event_logger = event_logger or EventLogger()
        self.detector_factory = detector_factory
        self.detector = None
        self.frame_jpeg = None
        self.notifications = deque(maxlen=200)
        self.snapshot = {
            'status': 'idle', 'mode': None, 'source': None, 'session_id': None,
            'students': [], 'elapsed': 0, 'progress': 0, 'fps': 0, 'error': None,
            'frame_width': 960, 'frame_height': 540, 'tracker': None,
            'stats': {'total_students': 0, 'total_events': 0, 'high_risk': 0, 'medium_risk': 0, 'low_risk': 0},
        }

    def status(self):
        with self.lock:
            return copy.deepcopy(self.snapshot)

    def start(self, source, source_label=None, seat_layout=None):
        with self.lock:
            if self.thread is not None and self.thread.is_alive():
                raise RuntimeError('Monitoring is already running or stopping.')
            mode = 'demo' if source == 'demo' else 'camera' if isinstance(source, int) else 'video'
            self.stop_event = threading.Event()
            self.notifications.clear()
            self.frame_jpeg = None
            self.snapshot.update(status='starting', source=source_label or str(source), mode=mode, session_id=uuid4().hex, students=[], elapsed=0, progress=0, fps=0, error=None)
            self.snapshot['stats'] = {'total_students': 0, 'total_events': 0, 'high_risk': 0, 'medium_risk': 0, 'low_risk': 0}
            self.thread = threading.Thread(target=self._run, args=(source, seat_layout), name='exam-monitor', daemon=True)
            self.thread.start()
            return copy.deepcopy(self.snapshot)

    def stop(self):
        with self.lock:
            thread = self.thread
            if thread is None or not thread.is_alive():
                return copy.deepcopy(self.snapshot)
            self.stop_event.set()
            self.snapshot['status'] = 'stopping'
        thread.join(timeout=8)
        return self.status()

    def read_frame(self):
        with self.lock:
            return self.frame_jpeg

    def drain_notifications(self):
        with self.lock:
            items = list(self.notifications)
            self.notifications.clear()
            return items

    def _run(self, source, seat_layout=None):
        capture = None
        try:
            is_demo = source == 'demo'
            seats = SeatManager(SEATS if is_demo else seat_layout)
            agent = ModelBasedAgent()
            tracker = StudentTracker()
            detectors = EventDetectorManager(seats)
            visualizer = Visualizer()
            fps_target = max(1, config.get('video.fps_target', 8))
            source_fps, frame_count, frame_number = fps_target, 0, 0
            session_id = self.snapshot['session_id']
            if not is_demo:
                if self.detector is None:
                    if self.detector_factory:
                        self.detector = self.detector_factory()
                    else:
                        from app.services.detector import PersonDetector
                        self.detector = PersonDetector()
                capture = cv2.VideoCapture(source)
                if not capture.isOpened():
                    raise RuntimeError('Cannot open this video source. Check the file or camera connection.')
                source_fps = capture.get(cv2.CAP_PROP_FPS)
                if not 1 <= source_fps <= 240:
                    source_fps = 25
                frame_count = max(0, capture.get(cv2.CAP_PROP_FRAME_COUNT))
            stride = max(1, config.get('video.frame_skip', 1), round(source_fps / fps_target))
            # ByteTrack's buffer and motion model should use the processed frame rate.
            if tracker.tracker is not None:
                tracker.tracker.frame_rate = max(1, round(source_fps / stride))
            with self.lock:
                self.snapshot.update(status='running', seats=seats.seats, tracker=tracker.backend)
            start_clock = time.monotonic()
            previous_tick = start_clock
            count_events = 0
            while not self.stop_event.is_set():
                tick = time.monotonic()
                if is_demo:
                    timestamp = tick - start_clock
                    frame, persons, phones = demo_frame(timestamp)
                else:
                    ok, frame = capture.read()
                    if not ok:
                        if frame_number == 0 or isinstance(source, int):
                            raise RuntimeError('The video source stopped providing frames.')
                        break
                    frame_number += 1
                    if (frame_number - 1) % stride:
                        continue
                    frame = resize_frame(frame)
                    timestamp = tick - start_clock if isinstance(source, int) else (frame_number - 1) / source_fps
                    persons, phones = self.detector.analyze(frame)
                tracks = tracker.update(persons, frame, timestamp)
                seats.assignments = {key: value for key, value in seats.assignments.items() if key in tracker.tracks}
                seats.assign_tracks(tracks)
                for track in tracks:
                    agent.register(track['track_id'], timestamp)
                observations = detectors.detect_all(tracks, {'frame': frame, 'phones': phones}, timestamp)
                events = agent.process_events(observations, timestamp)
                annotated = frame.copy()
                for seat_id, info in seats.seats.items():
                    occupied = any(track.get('seat_id') == seat_id and seats.is_in_seat(track['center'], seat_id) for track in tracks)
                    visualizer.draw_seat(annotated, seat_id, info['bbox'], occupied)
                students = []
                for track in tracks:
                    student = {**agent.get_student_info(track['track_id']), 'seat_id': track.get('seat_id'), 'bbox': track['bbox']}
                    students.append(student)
                    visualizer.draw_bbox(annotated, track['bbox'], track['track_id'], student['state'], student['risk_score'])
                saved_events = []
                for event in events:
                    saved_events.append(self.event_logger.log_event(event, annotated, session_id, is_demo))
                    count_events += 1
                if is_demo:
                    cv2.rectangle(annotated, (0, annotated.shape[0] - 28), (annotated.shape[1], annotated.shape[0]), (30, 30, 30), -1)
                    cv2.putText(annotated, 'SIMULATION - synthetic detections, no real people analyzed', (16, annotated.shape[0] - 9), cv2.FONT_HERSHEY_SIMPLEX, .45, (100, 220, 240), 1)
                ok, encoded = cv2.imencode('.jpg', annotated, [cv2.IMWRITE_JPEG_QUALITY, 80])
                now = time.monotonic()
                rate = 1 / max(.001, now - previous_tick)
                previous_tick = now
                stats = {
                    'total_students': len(students), 'total_events': count_events,
                    'high_risk': sum(student['state'] == 'ALERT' for student in students),
                    'medium_risk': sum(student['state'] == 'SUSPICIOUS' for student in students),
                    'low_risk': sum(student['state'] == 'OBSERVE' for student in students),
                }
                with self.lock:
                    if ok:
                        self.frame_jpeg = encoded.tobytes()
                    self.snapshot.update(students=students, elapsed=round(timestamp, 2), progress=min(100, round(frame_number / frame_count * 100, 1)) if frame_count else 0, fps=round(rate, 1), stats=stats, frame_width=frame.shape[1], frame_height=frame.shape[0])
                    self.notifications.extend(saved_events)
                pace = 1 / fps_target if is_demo or isinstance(source, int) else timestamp + stride / source_fps - (time.monotonic() - start_clock)
                self.stop_event.wait(max(0, pace))
            with self.lock:
                self.snapshot['status'] = 'stopped' if self.stop_event.is_set() else 'completed'
                if not self.stop_event.is_set() and not is_demo:
                    self.snapshot['progress'] = 100
        except Exception as error:
            logging.exception('Video processing failed')
            with self.lock:
                self.snapshot.update(status='error', error=str(error))
        finally:
            if capture is not None:
                capture.release()

