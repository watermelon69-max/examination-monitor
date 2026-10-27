import math
from collections import defaultdict, deque
from app.core.config import config


class BaseEventDetector:
    event_type = ''

    def __init__(self):
        self.last_emission = {}
        self.cooldown = config.get('events.cooldown_seconds', 5)

    def emit(self, track, timestamp, duration=0.0, confidence=0.8, **extra):
        key = track['track_id']
        if timestamp - self.last_emission.get(key, -float('inf')) < self.cooldown:
            return None
        self.last_emission[key] = timestamp
        return {'type': self.event_type, 'track_id': key, 'seat_id': track.get('seat_id'), 'bbox': track['bbox'], 'confidence': float(confidence), 'duration': duration, 'timestamp': timestamp, **extra}


class LeavingSeatDetector(BaseEventDetector):
    event_type = 'leaving_seat'

    def __init__(self, seat_manager):
        super().__init__()
        self.seat_manager = seat_manager
        self.outside_since = {}
        self.leave_threshold = config.get('seats.leave_threshold_seconds', 5)

    def detect(self, tracks, frame_data, timestamp):
        events = []
        self.seat_manager.assign_tracks(tracks)
        visible = {track['track_id'] for track in tracks}
        self.outside_since = {key: value for key, value in self.outside_since.items() if key in visible}
        for track in tracks:
            track_id, seat_id = track['track_id'], track.get('seat_id')
            if seat_id is None or self.seat_manager.is_in_seat(track['center'], seat_id):
                self.outside_since.pop(track_id, None)
                continue
            started = self.outside_since.setdefault(track_id, timestamp)
            if timestamp - started >= self.leave_threshold:
                event = self.emit(track, timestamp, timestamp - started, confidence=track['conf'])
                if event:
                    events.append(event)
        return events


class RepeatedTurningDetector(BaseEventDetector):
    event_type = 'repeated_turning'

    def __init__(self):
        super().__init__()
        self.turn_history = defaultdict(deque)
        self.orientation = {}
        self.candidate = {}
        self.threshold = config.get('events.head_turn.threshold_count', 3)
        self.window = config.get('events.head_turn.duration_window', 10)
        self.angle = config.get('events.head_turn.angle_threshold', 30)

    def detect(self, tracks, frame_data, timestamp):
        events = []
        for track in tracks:
            track_id = track['track_id']
            if 'head_yaw' not in track:
                continue
            yaw = track['head_yaw']
            side = 1 if yaw > self.angle else -1 if yaw < -self.angle else 0
            previous_side, since = self.candidate.get(track_id, (side, timestamp))
            if side != previous_side:
                self.candidate[track_id] = (side, timestamp)
                continue
            self.candidate.setdefault(track_id, (side, timestamp))
            if timestamp - since < 0.3:
                continue
            if side != self.orientation.get(track_id, 0):
                self.orientation[track_id] = side
                if side:
                    self.turn_history[track_id].append(timestamp)
            history = self.turn_history[track_id]
            while history and timestamp - history[0] > self.window:
                history.popleft()
            if len(history) >= self.threshold:
                event = self.emit(track, timestamp, timestamp - history[0], confidence=0.7, turn_count=len(history))
                if event:
                    events.append(event)
        return events


class MobilePhoneDetector(BaseEventDetector):
    event_type = 'mobile_phone'

    def __init__(self, detector=None):
        super().__init__()
        self.since = {}

    def detect(self, tracks, frame_data, timestamp):
        events = []
        seen = set()
        for phone in frame_data.get('phones', []):
            box = phone['bbox']
            center = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
            candidates = []
            for track in tracks:
                x1, y1, x2, y2 = track['bbox']
                if x1 <= center[0] <= x2 and y1 <= center[1] <= y2:
                    candidates.append((math.dist(center, track['center']), track))
            if not candidates:
                continue
            track = min(candidates, key=lambda item: item[0])[1]
            track_id = track['track_id']
            seen.add(track_id)
            since = self.since.setdefault(track_id, timestamp)
            if timestamp - since >= config.get('events.mobile_phone.duration_threshold', 1):
                event = self.emit(track, timestamp, timestamp - since, confidence=phone['conf'], phone_bbox=box)
                if event:
                    events.append(event)
        self.since = {key: value for key, value in self.since.items() if key in seen}
        return events


class GatheringDetector(BaseEventDetector):
    event_type = 'gathering'

    def __init__(self, seat_manager=None):
        super().__init__()
        self.seat_manager = seat_manager
        self.history = {}
        self.radius = config.get('events.gathering.cluster_radius', 200)
        self.minimum = config.get('events.gathering.min_cluster_size', 3)
        self.duration = config.get('events.gathering.duration_threshold', 10)

    def detect(self, tracks, frame_data, timestamp):
        # Adjacent seated students are expected. Calibration is needed for this rule.
        if self.seat_manager is None or not self.seat_manager.seats:
            return []
        eligible = [track for track in tracks if track.get('seat_id') is not None and not self.seat_manager.is_in_seat(track['center'], track['seat_id'])]
        pending = set(range(len(eligible)))
        active = set()
        events = []
        while pending:
            group = {pending.pop()}
            frontier = list(group)
            while frontier:
                index = frontier.pop()
                neighbors = {other for other in pending if math.dist(eligible[index]['center'], eligible[other]['center']) < self.radius}
                pending -= neighbors
                group |= neighbors
                frontier.extend(neighbors)
            if len(group) < self.minimum:
                continue
            members = [eligible[index] for index in sorted(group)]
            key = tuple(sorted(track['track_id'] for track in members))
            active.add(key)
            started = self.history.setdefault(key, timestamp)
            if timestamp - started >= self.duration:
                for track in members:
                    event = self.emit(track, timestamp, timestamp - started, track_ids=list(key))
                    if event:
                        events.append(event)
        self.history = {key: value for key, value in self.history.items() if key in active}
        return events


class UnusualMovementDetector(BaseEventDetector):
    event_type = 'unusual_movement'

    def __init__(self):
        super().__init__()
        self.history = defaultdict(lambda: deque(maxlen=100))

    def detect(self, tracks, frame_data, timestamp):
        events = []
        for track in tracks:
            history = self.history[track['track_id']]
            history.append((timestamp, track['center']))
            while history and timestamp - history[0][0] > 2:
                history.popleft()
            if len(history) < 4:
                continue
            velocities, vectors = [], []
            for (before, a), (after, b) in zip(history, list(history)[1:]):
                elapsed = after - before
                if elapsed > 0:
                    vectors.append(((b[0] - a[0]) / elapsed, (b[1] - a[1]) / elapsed))
                    velocities.append((after, math.dist(a, b) / elapsed))
            if not velocities:
                continue
            speed = max(value for _, value in velocities)
            acceleration = max((abs(b[1] - a[1]) / (b[0] - a[0]) for a, b in zip(velocities, velocities[1:]) if b[0] > a[0]), default=0)
            turns = sum(ax * bx + ay * by < 0 and math.hypot(ax, ay) > 30 and math.hypot(bx, by) > 30 for (ax, ay), (bx, by) in zip(vectors, vectors[1:]))
            rapid = speed > config.get('events.unusual_movement.velocity_threshold', 200)
            erratic = turns >= config.get('events.unusual_movement.erratic_threshold', 3) and acceleration > config.get('events.unusual_movement.acceleration_threshold', 500)
            if rapid or erratic:
                event = self.emit(track, timestamp, timestamp - history[0][0], confidence=0.7, max_velocity=speed)
                if event:
                    events.append(event)
        visible = {track['track_id'] for track in tracks}
        for track_id in list(self.history):
            if track_id not in visible:
                del self.history[track_id]
        return events


class EventDetectorManager:
    def __init__(self, seat_manager, detector=None):
        self.detectors = [LeavingSeatDetector(seat_manager), RepeatedTurningDetector(), MobilePhoneDetector(detector), GatheringDetector(seat_manager), UnusualMovementDetector()]

    def detect_all(self, tracks, frame_data, timestamp):
        events = []
        for detector in self.detectors:
            events.extend(detector.detect(tracks, frame_data, timestamp))
        return events
