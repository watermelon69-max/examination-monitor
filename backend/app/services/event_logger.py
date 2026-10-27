from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
import cv2
from sqlalchemy import select, func
from app.models.database import DATA_DIR, SessionLocal, Event
from app.core.config import config


class EventLogger:
    def __init__(self):
        self.evidence_dir = DATA_DIR / 'evidence'
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        self.saved = 0

    @staticmethod
    def serialize(event):
        filename = Path(event.evidence_frame_path).name if event.evidence_frame_path else None
        return {
            'id': event.id, 'timestamp': event.timestamp.isoformat() + 'Z' if event.timestamp.tzinfo is None else event.timestamp.isoformat(),
            'time_str': event.time_str, 'student_id': event.student_id, 'seat_id': event.seat_id,
            'event_type': event.event_type, 'confidence': event.confidence, 'risk_level': event.risk_level,
            'risk_score': event.risk_score, 'duration': event.duration, 'reasoning': event.reasoning,
            'state': event.state, 'session_id': event.session_id, 'is_demo': bool(event.is_demo),
            'video_time': event.video_time or 0, 'evidence_url': f'/api/evidence/{filename}' if filename else None,
        }

    def log_event(self, event, frame, session_id='', is_demo=False):
        moment = datetime.now(timezone.utc)
        evidence_path = None
        self.saved += 1
        if config.get('evidence.save_frames', True) and frame is not None and (self.saved - 1) % max(1, config.get('evidence.save_interval', 1)) == 0:
            filename = f'{session_id[:8]}_{uuid4().hex}.jpg'
            target = self.evidence_dir / filename
            annotated = frame.copy()
            x1, y1, x2, y2 = map(int, event['bbox'])
            cv2.rectangle(annotated, (x1, y1), (x2, y2), (30, 75, 245), 3)
            label = ('SIMULATION | ' if is_demo else '') + f"{event['type']} | student {event['track_id']}"
            cv2.putText(annotated, label, (max(5, x1), max(25, y1 - 12)), cv2.FONT_HERSHEY_SIMPLEX, .6, (30, 75, 245), 2)
            if cv2.imwrite(str(target), annotated, [cv2.IMWRITE_JPEG_QUALITY, config.get('evidence.quality', 85)]):
                evidence_path = filename
        score = event.get('total_risk', 0)
        level = 'High' if score >= config.get('agent.alert_threshold', 70) else 'Medium' if score >= config.get('agent.suspicious_threshold', 40) else 'Low' if score >= config.get('agent.observe_threshold', 15) else 'Minimal'
        stored = Event(timestamp=moment, time_str=moment.strftime('%Y-%m-%d %H:%M:%S UTC'), student_id=int(event['track_id']), seat_id=event.get('seat_id'), event_type=event['type'], confidence=float(event.get('confidence', 0)), risk_level=level, risk_score=score, duration=event.get('duration', 0), reasoning=event.get('reasoning', ''), evidence_frame_path=evidence_path, bbox_x1=float(event['bbox'][0]), bbox_y1=float(event['bbox'][1]), bbox_x2=float(event['bbox'][2]), bbox_y2=float(event['bbox'][3]), state=event.get('current_state', 'NORMAL'), session_id=session_id, is_demo=is_demo, video_time=event['timestamp'])
        with SessionLocal() as database:
            database.add(stored)
            database.commit()
            result = self.serialize(stored)
        if self.saved % 20 == 0:
            self.prune_evidence()
        return result

    def prune_evidence(self):
        files = sorted(self.evidence_dir.glob('*.jpg'), key=lambda path: path.stat().st_mtime)
        total = sum(path.stat().st_size for path in files)
        maximum = config.get('evidence.max_storage_gb', 5) * 1024 ** 3
        for path in files:
            if total <= maximum:
                break
            total -= path.stat().st_size
            path.unlink(missing_ok=True)

    def get_events(self, limit=100, offset=0, risk_level=None, student_id=None, event_type=None, session_id=None, is_demo=None):
        conditions = []
        for column, value in [(Event.risk_level, risk_level), (Event.student_id, student_id), (Event.event_type, event_type), (Event.session_id, session_id), (Event.is_demo, is_demo)]:
            if value is not None:
                conditions.append(column == value)
        with SessionLocal() as database:
            total = database.scalar(select(func.count()).select_from(Event).where(*conditions))
            rows = database.scalars(select(Event).where(*conditions).order_by(Event.id.desc()).offset(offset).limit(limit)).all()
            return {'total': total, 'events': [self.serialize(row) for row in rows]}
