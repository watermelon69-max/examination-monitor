from app.services.seat_manager import SeatManager
from app.services.event_detectors import LeavingSeatDetector, RepeatedTurningDetector, MobilePhoneDetector, GatheringDetector
from app.services.tracker import StudentTracker


def track(x=50, y=50, track_id=1, yaw=None):
    item = {'track_id': track_id, 'center': [x, y], 'bbox': [x-20, y-40, x+20, y+40], 'conf': .95}
    if yaw is not None:
        item['head_yaw'] = yaw
    return item


def test_leaving_seat_remembers_assignment_outside_association_radius():
    seats = SeatManager({})
    seats.add_seat(1, [0, 0, 100, 100])
    detector = LeavingSeatDetector(seats)
    detector.detect([track()], {}, 0)
    assert detector.detect([track(400)], {}, 1) == []
    result = detector.detect([track(400)], {}, 7)
    assert result[0]['seat_id'] == 1
    assert result[0]['duration'] == 6
    assert detector.detect([track(400)], {}, 8) == []
    assert detector.detect([track()], {}, 9) == []
    assert detector.detect([track(400)], {}, 10) == []


def test_seats_are_exclusive():
    seats = SeatManager({})
    seats.add_seat(1, [0, 0, 100, 100])
    items = [track(track_id=1), track(track_id=2)]
    seats.assign_tracks(items)
    assert [item['seat_id'] for item in items] == [1, None]


def test_phone_uses_measured_confidence_and_requires_sustained_presence():
    detector = MobilePhoneDetector()
    phones = {'phones': [{'bbox': [45, 45, 55, 55], 'conf': .63}]}
    assert detector.detect([track()], phones, 0) == []
    result = detector.detect([track()], phones, 1.1)
    assert result[0]['confidence'] == .63
    assert detector.detect([track()], phones, 2) == []
    detector.detect([track()], {}, 3)
    assert detector.detect([track()], phones, 9) == []


def test_turning_ignores_body_movement_and_expired_turns():
    detector = RepeatedTurningDetector()
    for index in range(20):
        assert detector.detect([track(50 + (-1)**index * 20)], {}, index / 10) == []
    for timestamp, yaw in [(0, 45), (.4, 45), (1, -45), (1.4, -45), (15, 45), (15.4, 45)]:
        assert detector.detect([track(yaw=yaw)], {}, timestamp) == []


def test_gathering_ignores_seated_students_and_resets_after_gap():
    seats = SeatManager({})
    for index, x in enumerate([50, 150, 250], 1):
        seats.add_seat(index, [x-40, 0, x+40, 100])
    students = [track(x, track_id=index) for index, x in enumerate([50, 150, 250], 1)]
    seats.assign_tracks(students)
    detector = GatheringDetector(seats)
    assert detector.detect(students, {}, 0) == []
    assert detector.detect(students, {}, 20) == []
    moved = [track(400 + index * 30, 200, index) for index in [1, 2, 3]]
    seats.assign_tracks(moved)
    assert detector.detect(moved, {}, 21) == []
    assert len(detector.detect(list(reversed(moved)), {}, 32)) == 3
    detector.detect([], {}, 33)
    assert detector.detect(moved, {}, 50) == []


def test_fallback_tracking_survives_reordering_and_short_occlusion():
    tracker = StudentTracker()
    tracker.tracker = None
    first = tracker.update([track(50), track(300)], timestamp=0)
    second = tracker.update([track(305), track(55)], timestamp=1)
    assert second[0]['track_id'] == first[1]['track_id']
    assert second[1]['track_id'] == first[0]['track_id']
    tracker.update([], timestamp=2)
    third = tracker.update([track(60)], timestamp=3)
    assert third[0]['track_id'] == first[0]['track_id']
    assert tracker.get_history(third[0]['track_id'])[-1]['frame_time'] == 3
