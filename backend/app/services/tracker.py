from collections import defaultdict, deque
import math
from app.core.config import config


def intersection_over_union(a, b):
    width = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    height = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    intersection = width * height
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - intersection
    return intersection / union if union > 0 else 0.0


class StudentTracker:
    """ByteTrack when available, with a persistent IoU/centroid fallback."""
    def __init__(self):
        self.tracks = {}
        self.track_history = defaultdict(lambda: deque(maxlen=100))
        self.next_id = 1
        self.track_buffer = config.get('tracking.track_buffer', 30)
        self.tracker = None
        self.backend = 'IoU / centroid'
        if config.get('tracking.tracker', 'bytetrack') == 'bytetrack':
            try:
                import supervision as sv
                from trackers import ByteTrackTracker
                self.sv = sv
                self.tracker = ByteTrackTracker(track_activation_threshold=config.get('tracking.track_threshold', 0.5), lost_track_buffer=self.track_buffer, frame_rate=config.get('video.fps_target', 8), minimum_consecutive_frames=1, minimum_iou_threshold=1 - config.get('tracking.match_threshold', 0.8))
                self.backend = 'ByteTrack'
            except ImportError:
                pass

    def update(self, detections, frame=None, timestamp=0.0):
        import numpy as np
        if self.tracker is not None:
            items = self.sv.Detections(xyxy=np.asarray([d['bbox'] for d in detections], dtype=float).reshape(-1, 4), confidence=np.asarray([d['conf'] for d in detections], dtype=float), class_id=np.zeros(len(detections), dtype=int))
            tracked = self.tracker.update(items, timestamp=timestamp)
            result = []
            for bbox, conf, track_id in zip(tracked.xyxy, tracked.confidence, tracked.tracker_id):
                if track_id < 0:
                    continue
                matched = max(detections, key=lambda detection: intersection_over_union(bbox, detection['bbox']), default={})
                result.append({**matched, 'track_id': int(track_id), 'bbox': bbox.tolist(), 'conf': float(conf)})
        else:
            candidates = []
            for track_id, previous in self.tracks.items():
                for index, detection in enumerate(detections):
                    box = detection['bbox']
                    center = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
                    distance = math.dist(previous['center'], center)
                    iou = intersection_over_union(previous['bbox'], box)
                    if iou > 0.1 or distance < 100:
                        candidates.append((iou - distance / 1000, track_id, index))
            matches, used = {}, set()
            for _, track_id, index in sorted(candidates, reverse=True):
                if index not in matches and track_id not in used:
                    matches[index] = track_id
                    used.add(track_id)
            result = []
            for index, detection in enumerate(detections):
                track_id = matches.get(index)
                if track_id is None:
                    track_id = self.next_id
                    self.next_id += 1
                result.append({**detection, 'track_id': track_id})
        visible = set()
        for track in result:
            bbox = track['bbox']
            track['center'] = [(bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2]
            track['bbox'] = [float(value) for value in bbox]
            track_id = track['track_id']
            visible.add(track_id)
            self.tracks[track_id] = {**track, 'missed': 0}
            self.track_history[track_id].append({'bbox': track['bbox'], 'center': track['center'], 'frame_time': timestamp})
        for track_id in list(self.tracks):
            if track_id not in visible:
                self.tracks[track_id]['missed'] += 1
                if self.tracks[track_id]['missed'] > self.track_buffer:
                    del self.tracks[track_id]
                    self.track_history.pop(track_id, None)
        return result

    def get_history(self, track_id):
        return list(self.track_history[track_id])
