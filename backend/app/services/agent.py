from collections import defaultdict, deque
from enum import IntEnum
from app.core.config import config


class StudentState(IntEnum):
    NORMAL = 0
    OBSERVE = 1
    SUSPICIOUS = 2
    ALERT = 3


class ModelBasedAgent:
    """Deterministic time-based reasoning using elapsed video seconds."""
    def __init__(self):
        self.student_states = {}
        self.student_risk_scores = defaultdict(float)
        self.student_memory = defaultdict(lambda: deque(maxlen=1000))
        self.state_history = defaultdict(lambda: deque(maxlen=200))
        self.last_update = None
        self.last_event = {}
        self.memory_window = config.get('agent.memory_window_seconds', 60)
        self.decay_rate = config.get('agent.decay_rate', 0.1)
        self.thresholds = [config.get('agent.observe_threshold', 15), config.get('agent.suspicious_threshold', 40), config.get('agent.alert_threshold', 70)]
        self.min_duration_in_state = config.get('agent.min_duration_in_state', 2)
        self.weights = config.get('risk_scoring.weights', {})
        self.event_type_scores = config.get('risk_scoring.event_type_scores', {})
        self.current_time = 0.0

    def register(self, track_id, timestamp):
        if track_id not in self.student_states:
            self.student_states[track_id] = StudentState.NORMAL
            self.student_risk_scores[track_id] = 0.0
            self.state_history[track_id].append({'state': StudentState.NORMAL, 'timestamp': timestamp})

    def process_events(self, events, timestamp):
        self.apply_decay(timestamp)
        for event in events:
            track_id = event['track_id']
            self.register(track_id, timestamp)
            self.student_memory[track_id].append({'event': dict(event), 'timestamp': timestamp})
            frequency = len(self.get_recent_events(track_id, timestamp, self.memory_window))
            increase = self.calculate_risk_score(event, frequency)
            self.student_risk_scores[track_id] = min(100.0, self.student_risk_scores[track_id] + increase)
            self.last_event[track_id] = timestamp
            event.update(risk_increase=increase, total_risk=self.student_risk_scores[track_id], reasoning=self.generate_reasoning(track_id, event))
        for track_id in self.student_states:
            self.update_state(track_id, timestamp)
        for event in events:
            event['current_state'] = self.student_states[event['track_id']].name
        self.current_time = timestamp
        return events

    def calculate_risk_score(self, event, frequency=1):
        confidence = max(0.0, min(1.0, event.get('confidence', 0.5)))
        duration = min(max(event.get('duration', 0), 0) / 30, 1.0)
        repetition = min(max(frequency - 1, 0) / 5, 1.0)
        base = self.event_type_scores.get(event['type'], 10)
        return base * (1 + self.weights.get('confidence', 0.25) * (confidence - 0.5) + self.weights.get('duration', 0.25) * duration + self.weights.get('frequency', 0.3) * repetition) * (0.8 + self.weights.get('event_type', 0.2))

    def apply_decay(self, timestamp):
        previous = self.last_update
        self.last_update = timestamp
        if previous is None:
            return
        for track_id in self.student_states:
            idle_start = max(previous, self.last_event.get(track_id, previous) + 5)
            elapsed = max(0, timestamp - idle_start)
            self.student_risk_scores[track_id] = max(0.0, self.student_risk_scores[track_id] - self.decay_rate * elapsed)
            memory = self.student_memory[track_id]
            while memory and timestamp - memory[0]['timestamp'] > self.memory_window:
                memory.popleft()

    def update_state(self, track_id, timestamp):
        score = self.student_risk_scores[track_id]
        target = StudentState(sum(score >= threshold for threshold in self.thresholds))
        current = self.student_states[track_id]
        if target == current or timestamp - self.state_history[track_id][-1]['timestamp'] < self.min_duration_in_state:
            return
        if target < current and score >= self.thresholds[int(current) - 1] - 2:
            return
        self.student_states[track_id] = target
        self.state_history[track_id].append({'state': target, 'timestamp': timestamp, 'risk_score': score})

    def get_recent_events(self, track_id, current_time, window_seconds):
        return [observation for observation in self.student_memory[track_id] if 0 <= current_time - observation['timestamp'] <= window_seconds]

    def generate_reasoning(self, track_id, event):
        duration = event.get('duration', 0)
        explanations = {
            'leaving_seat': f"Outside assigned seat for {duration:.1f}s",
            'repeated_turning': f"Head orientation changed {event.get('turn_count', 0)} times in {duration:.1f}s",
            'mobile_phone': f"Phone detected within student's bounding box for {duration:.1f}s",
            'gathering': f"Group of {len(event.get('track_ids', []))} students away from assigned seats for {duration:.1f}s",
            'unusual_movement': f"Rapid or erratic movement: {event.get('max_velocity', 0):.0f} px/s",
        }
        count = len(self.get_recent_events(track_id, event['timestamp'], 30))
        return explanations.get(event['type'], 'Behavior observation') + (f'; {count} observations in 30s' if count > 1 else '')

    def get_student_info(self, track_id):
        return {'track_id': track_id, 'state': self.student_states.get(track_id, StudentState.NORMAL).name, 'risk_score': round(self.student_risk_scores.get(track_id, 0), 2), 'recent_events': len(self.get_recent_events(track_id, self.current_time, self.memory_window))}

    def get_alert_students(self):
        return [self.get_student_info(track_id) for track_id, state in self.student_states.items() if state >= StudentState.SUSPICIOUS]
