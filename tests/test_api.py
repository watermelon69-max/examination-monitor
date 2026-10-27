import time
import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient
import main
from app.models.database import DATA_DIR


@pytest.fixture
def client():
    with TestClient(main.app) as connection:
        yield connection
        main.monitor.stop()


def make_video():
    path = DATA_DIR / 'fixture.avi'
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'MJPG'), 8, (320, 240))
    assert writer.isOpened()
    for index in range(24):
        image = np.full((240, 320, 3), index * 5, np.uint8)
        cv2.rectangle(image, (50, 50), (110, 180), (100, 150, 200), -1)
        writer.write(image)
    writer.release()
    return path.read_bytes()


def test_dashboard_health_and_bad_upload(client):
    assert client.get('/').status_code == 200
    assert 'Exam Sentinel' in client.get('/').text
    assert client.get('/api/health').json()['status'] == 'healthy'
    assert client.get('/static/js/app.js').status_code == 200
    assert client.post('/api/videos', files={'file': ('bad.txt', b'bad', 'text/plain')}).status_code == 400
    assert client.post('/api/videos', files={'file': ('bad.mp4', b'not a video', 'video/mp4')}).status_code == 400
    assert client.post('/api/start', json={'source': '../missing.mp4'}).status_code == 400


def test_upload_seats_and_preview_round_trip(client):
    response = client.post('/api/videos', files={'file': ('recording.avi', make_video(), 'video/avi')})
    assert response.status_code == 201, response.text
    video = response.json()
    assert video['width'] == 320
    assert client.get(video['preview_url']).headers['content-type'] == 'image/jpeg'
    layout = {'source': video['id'], 'width': 320, 'height': 240, 'seats': {'1': [30, 20, 130, 200]}}
    assert client.put('/api/seats', json=layout).status_code == 200
    result = client.get('/api/seats', params={'source': video['id']}).json()
    assert result['seats']['1']['center'] == [80, 110]
    layout['seats']['1'][2] = 500
    assert client.put('/api/seats', json=layout).status_code == 400
    assert any(item['id'] == video['id'] for item in client.get('/api/videos').json())


def test_demo_lifecycle_conflict_and_websocket(client):
    response = client.post('/api/start', json={'source': 'demo'})
    assert response.status_code == 200
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        status = client.get('/api/status').json()
        if status['students'] or status['status'] == 'error':
            break
        time.sleep(.1)
    assert status['status'] == 'running', status
    assert len(status['students']) == 6
    assert status['tracker'] == 'ByteTrack'
    assert main.monitor.read_frame()[:2] == b'\xff\xd8'
    assert client.post('/api/start', json={'source': 'demo'}).status_code == 409
    assert client.put('/api/seats', json={'source': 'demo', 'width': 960, 'height': 540, 'seats': {}}).status_code == 409
    with client.websocket_connect('/ws') as websocket:
        assert websocket.receive_json()['type'] == 'status'
        websocket.send_json({'type': 'ping'})
        while websocket.receive_json()['type'] != 'pong':
            pass
        websocket.send_json({'type': 'unsupported'})
        while websocket.receive_json()['type'] != 'error':
            pass
    assert client.post('/api/stop').json()['status'] == 'stopped'
    new = client.post('/api/start', json={'source': 'demo'}).json()
    assert new['session_id'] != status['session_id']


def test_events_filter_export_and_evidence(client):
    event = {'type': 'mobile_phone', 'track_id': 77, 'seat_id': 4, 'confidence': .83, 'duration': 2, 'timestamp': 14, 'bbox': [10, 10, 50, 80], 'total_risk': 75, 'current_state': 'ALERT', 'reasoning': 'Test observation'}
    saved = main.event_logger.log_event(event, np.zeros((100, 100, 3), np.uint8), 'test-session', True)
    result = client.get('/api/events', params={'student_id': 77, 'risk_level': 'High', 'session_id': 'test-session', 'is_demo': True}).json()
    assert result['total'] == 1
    assert result['events'][0]['id'] == saved['id']
    assert client.get(saved['evidence_url']).content[:2] == b'\xff\xd8'
    assert client.get('/api/evidence/missing.jpg').status_code == 404
    export = client.get('/api/events/export', params={'session_id': 'test-session'})
    assert 'test-session' in export.text
    assert 'text/csv' in export.headers['content-type']


def test_video_pipeline_completes_and_can_restart(client):
    response = client.post('/api/videos', files={'file': ('empty-hall.avi', make_video(), 'video/avi')})
    source = response.json()['id']

    class ControlledDetector:
        def analyze(self, frame):
            return [], []

    original_factory, original_detector = main.monitor.detector_factory, main.monitor.detector
    main.monitor.detector_factory = ControlledDetector
    main.monitor.detector = None
    try:
        assert client.post('/api/start', json={'source': source}).status_code == 200
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            status = client.get('/api/status').json()
            if status['status'] in ('completed', 'error'):
                break
            time.sleep(.1)
        assert status['status'] == 'completed', status
        assert status['progress'] == 100
        assert status['elapsed'] == pytest.approx(2.875, abs=.01)
        assert client.post('/api/start', json={'source': 'demo'}).status_code == 200
        main.monitor.stop()
    finally:
        main.monitor.detector_factory, main.monitor.detector = original_factory, original_detector

