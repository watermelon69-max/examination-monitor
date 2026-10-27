import json
import math
from app.core.config import config


class SeatManager:
    def __init__(self, seats=None):
        self.seats_path = config.project_root / config.get('seats.config_file', 'config/seats.json')
        self.assignments = {}
        self.seats = {}
        if seats is None:
            self.load_seats()
        else:
            self.seats = {int(key): value for key, value in seats.items()}

    def load_seats(self):
        if self.seats_path.exists():
            data = json.loads(self.seats_path.read_text(encoding='utf-8'))
            self.seats = {int(key): value for key, value in data.items()}

    def save_seats(self):
        self.seats_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.seats_path.with_suffix('.tmp')
        temporary.write_text(json.dumps(self.seats, indent=2), encoding='utf-8')
        temporary.replace(self.seats_path)

    def add_seat(self, seat_id, bbox):
        self.seats[int(seat_id)] = {'bbox': list(bbox), 'center': [(bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2]}

    def associate_track_to_seat(self, track_center):
        candidates = [(math.dist(track_center, seat['center']), seat_id) for seat_id, seat in self.seats.items()]
        distance, seat_id = min(candidates, default=(float('inf'), None))
        return seat_id if distance <= config.get('seats.association_radius', 150) else None

    def assign_tracks(self, tracks):
        occupied = set(self.assignments.values())
        for track in tracks:
            track_id = track['track_id']
            if track_id not in self.assignments:
                candidates = [(math.dist(track['center'], seat['center']), seat_id) for seat_id, seat in self.seats.items() if seat_id not in occupied and self.is_in_seat(track['center'], seat_id)]
                if candidates:
                    seat_id = min(candidates)[1]
                    self.assignments[track_id] = seat_id
                    occupied.add(seat_id)
            track['seat_id'] = self.assignments.get(track_id)
        return tracks

    def is_in_seat(self, track_center, seat_id):
        if seat_id not in self.seats:
            return False
        x1, y1, x2, y2 = self.seats[seat_id]['bbox']
        return x1 <= track_center[0] <= x2 and y1 <= track_center[1] <= y2
