import asyncio
import csv
import io
import json
import math
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from uuid import uuid4
import cv2
from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from app.core.config import config
from app.models.database import DATA_DIR, initialize_database
from app.services.event_logger import EventLogger
from app.services.monitor import MonitoringService, resize_frame
from app.services.demo import demo_frame, SEATS

PROJECT_ROOT = config.project_root
VIDEO_DIR = DATA_DIR / 'videos'
LAYOUT_DIR = DATA_DIR / 'layouts'
for directory in (VIDEO_DIR, LAYOUT_DIR, DATA_DIR / 'evidence'):
    directory.mkdir(parents=True, exist_ok=True)
VIDEO_EXTENSIONS = {'.mp4', '.avi', '.mov', '.mkv', '.webm', '.m4v'}


class ConnectionManager:
    def __init__(self):
        self.active_connections = set()

    async def connect(self, websocket):
        await websocket.accept()
        self.active_connections.add(websocket)

    def disconnect(self, websocket):
        self.active_connections.discard(websocket)

    async def broadcast(self, message):
        async def deliver(connection):
            try:
                await asyncio.wait_for(connection.send_json(message), timeout=1)
            except Exception:
                self.disconnect(connection)
        await asyncio.gather(*(deliver(connection) for connection in list(self.active_connections)))


manager = ConnectionManager()
event_logger = EventLogger()
monitor = MonitoringService(event_logger)


async def publish():
    while True:
        await manager.broadcast({'type': 'status', 'data': monitor.status()})
        for event in monitor.drain_notifications():
            await manager.broadcast({'type': 'alert', 'alert': event})
        await asyncio.sleep(.3)


@asynccontextmanager
async def lifespan(app):
    initialize_database()
    task = asyncio.create_task(publish())
    yield
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
    await asyncio.to_thread(monitor.stop)


app = FastAPI(title='Examination Hall Monitoring', version='2.0.0', lifespan=lifespan)
app.mount('/static', StaticFiles(directory=str(PROJECT_ROOT / 'frontend/static')), name='static')
templates = Jinja2Templates(directory=str(PROJECT_ROOT / 'frontend/templates'))


@app.get('/', response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse(request=request, name='index.html', context={})


@app.get('/api/health')
def health():
    import importlib.util
    return {'status': 'healthy', 'vision_ready': importlib.util.find_spec('ultralytics') is not None and all((PROJECT_ROOT / 'models' / name).exists() for name in (config.get('detection.model', 'yolov8n.pt'), config.get('detection.pose_model', 'yolov8n-pose.pt'))), 'monitoring': monitor.status()['status']}


@app.get('/api/status')
def status():
    return monitor.status()


@app.get('/api/students')
def students():
    return monitor.status()['students']


def video_path(video_id):
    if Path(video_id).name != video_id or '\\' in video_id or Path(video_id).suffix.lower() not in VIDEO_EXTENSIONS:
        raise HTTPException(400, 'Invalid video identifier.')
    path = VIDEO_DIR / video_id
    if not path.is_file():
        raise HTTPException(404, 'Video not found. Upload it first.')
    return path


def resolve_source(source):
    if source == 'demo':
        return 'demo'
    if source.startswith('camera:'):
        try:
            camera_id = int(source.split(':')[1])
        except ValueError:
            raise HTTPException(400, 'Invalid camera identifier.')
        if not 0 <= camera_id <= 10:
            raise HTTPException(400, 'Camera identifier must be between 0 and 10.')
        return camera_id
    return str(video_path(source))


def layout_path(source):
    resolve_source(source)
    return LAYOUT_DIR / (source.replace(':', '_') + '.json')


def load_layout(source):
    if source == 'demo':
        return {'seats': SEATS, 'width': 960, 'height': 540, 'source': 'demo'}
    path = layout_path(source)
    if path.exists():
        return json.loads(path.read_text(encoding='utf-8'))
    return {'seats': {}, 'source': source}


def describe_video(path, name=None):
    capture = cv2.VideoCapture(str(path))
    try:
        ok, frame = capture.read()
        if not ok:
            raise ValueError('This file could not be decoded as video.')
        frame = resize_frame(frame)
        fps = capture.get(cv2.CAP_PROP_FPS)
        fps = fps if 1 <= fps <= 240 else 25
        count = max(0, capture.get(cv2.CAP_PROP_FRAME_COUNT))
        preview_path = path.with_suffix('.jpg')
        if not cv2.imwrite(str(preview_path), frame):
            raise ValueError('Could not create a preview.')
        return {'id': path.name, 'name': name or path.name, 'width': frame.shape[1], 'height': frame.shape[0], 'fps': fps, 'duration': round(count / fps, 2), 'preview_url': f'/api/videos/{path.name}/preview'}
    finally:
        capture.release()


@app.get('/api/videos')
def videos():
    items = []
    for path in VIDEO_DIR.glob('*.json'):
        with suppress(ValueError, OSError):
            item = json.loads(path.read_text(encoding='utf-8'))
            if (VIDEO_DIR / item['id']).is_file():
                items.append(item)
    return sorted(items, key=lambda item: item['name'].lower())


@app.post('/api/videos', status_code=201)
async def upload_video(file: UploadFile = File(...)):
    suffix = Path(file.filename or '').suffix.lower()
    if suffix not in VIDEO_EXTENSIONS:
        raise HTTPException(400, 'Choose an MP4, AVI, MOV, MKV, WebM or M4V video.')
    path = VIDEO_DIR / (uuid4().hex + suffix)
    maximum = config.get('video.max_upload_mb', 512) * 1024 ** 2
    size = 0
    try:
        with path.open('wb') as handle:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > maximum:
                    raise HTTPException(413, f'Video exceeds the {maximum // 1024 ** 2} MB upload limit.')
                handle.write(chunk)
        metadata = await asyncio.to_thread(describe_video, path, file.filename)
        path.with_suffix('.json').write_text(json.dumps(metadata), encoding='utf-8')
        return metadata
    except Exception as error:
        path.unlink(missing_ok=True)
        path.with_suffix('.jpg').unlink(missing_ok=True)
        if isinstance(error, HTTPException):
            raise
        raise HTTPException(400, str(error))
    finally:
        await file.close()


@app.get('/api/videos/{video_id}/preview')
def video_preview(video_id: str):
    path = video_path(video_id)
    preview = path.with_suffix('.jpg')
    if not preview.exists():
        describe_video(path)
    return FileResponse(preview, media_type='image/jpeg')


@app.get('/api/demo/preview')
def demo_preview():
    frame, _, _ = demo_frame(0)
    _, encoded = cv2.imencode('.jpg', frame)
    return Response(encoded.tobytes(), media_type='image/jpeg')


@app.get('/api/camera/preview')
def camera_preview(camera: int = Query(0, ge=0, le=10)):
    if monitor.status()['status'] in ('starting', 'running', 'stopping'):
        raise HTTPException(409, 'Stop monitoring before previewing a camera.')
    capture = cv2.VideoCapture(camera)
    try:
        ok, frame = capture.read()
        if not ok:
            raise HTTPException(400, 'Camera unavailable. Connect a camera to this computer or upload a video.')
        frame = resize_frame(frame)
        _, encoded = cv2.imencode('.jpg', frame)
        return Response(encoded.tobytes(), media_type='image/jpeg')
    finally:
        capture.release()


@app.get('/api/seats')
def seats(source: str = 'demo'):
    return load_layout(source)


class SeatLayout(BaseModel):
    source: str
    width: int = Field(ge=1, le=8192)
    height: int = Field(ge=1, le=8192)
    seats: dict[int, list[float]]


@app.put('/api/seats')
def save_seats(layout: SeatLayout):
    if monitor.status()['status'] in ('starting', 'running', 'stopping'):
        raise HTTPException(409, 'Stop monitoring before changing the seat layout.')
    if layout.source == 'demo':
        raise HTTPException(400, 'The simulation uses its own seat layout. Select a video to calibrate.')
    if len(layout.seats) > 300:
        raise HTTPException(400, 'Maximum 300 seats.')
    if not layout.source.startswith('camera:'):
        path = video_path(layout.source)
        metadata = describe_video(path)
        if (metadata['width'], metadata['height']) != (layout.width, layout.height):
            raise HTTPException(400, 'Seat coordinates must match the processed preview dimensions.')
    manager_seats = {}
    for seat_id, box in layout.seats.items():
        if seat_id < 1 or len(box) != 4 or not all(math.isfinite(value) for value in box):
            raise HTTPException(400, 'Seats require a positive ID and four finite coordinates.')
        x1, y1, x2, y2 = box
        if not (0 <= x1 < x2 <= layout.width and 0 <= y1 < y2 <= layout.height):
            raise HTTPException(400, 'Seat rectangles must fit inside the image.')
        manager_seats[seat_id] = {'bbox': box, 'center': [(x1 + x2) / 2, (y1 + y2) / 2]}
    result = {'source': layout.source, 'width': layout.width, 'height': layout.height, 'seats': manager_seats}
    path = layout_path(layout.source)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(result, indent=2), encoding='utf-8')
    temporary.replace(path)
    return result


class StartRequest(BaseModel):
    source: str = 'demo'


def start_monitoring(source):
    actual_source = resolve_source(source)
    layout = load_layout(source)
    try:
        return monitor.start(actual_source, source, layout['seats'])
    except RuntimeError as error:
        raise HTTPException(409, str(error))


@app.post('/api/start')
def start(request: StartRequest):
    return start_monitoring(request.source)


@app.post('/api/stop')
async def stop():
    return await asyncio.to_thread(monitor.stop)


@app.get('/api/events')
def events(limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0), risk_level: str | None = None, student_id: int | None = None, event_type: str | None = None, session_id: str | None = None, is_demo: bool | None = None):
    return event_logger.get_events(limit, offset, risk_level, student_id, event_type, session_id, is_demo)


@app.get('/api/events/export')
def export_events(session_id: str | None = None, is_demo: bool | None = None):
    output = io.StringIO()
    fields = ['id', 'timestamp', 'student_id', 'seat_id', 'event_type', 'confidence', 'risk_level', 'risk_score', 'duration', 'reasoning', 'state', 'session_id', 'is_demo', 'video_time', 'evidence_url']
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction='ignore')
    writer.writeheader()
    offset = 0
    while True:
        batch = event_logger.get_events(limit=1000, offset=offset, session_id=session_id, is_demo=is_demo)['events']
        if not batch:
            break
        writer.writerows(batch)
        offset += len(batch)
    return Response(output.getvalue(), media_type='text/csv', headers={'Content-Disposition': 'attachment; filename="exam-events.csv"'})


@app.get('/api/evidence/{filename}')
def evidence(filename: str):
    if Path(filename).name != filename or '\\' in filename or not filename.endswith('.jpg'):
        raise HTTPException(400, 'Invalid evidence identifier.')
    path = DATA_DIR / 'evidence' / filename
    if not path.is_file():
        raise HTTPException(404, 'Evidence is unavailable or has expired under the storage limit.')
    return FileResponse(path, media_type='image/jpeg')


@app.get('/api/video/stream')
async def stream(request: Request):
    async def frames():
        previous = None
        while not await request.is_disconnected():
            frame = monitor.read_frame()
            if frame and frame is not previous:
                previous = frame
                yield b'--frame\r\nContent-Type: image/jpeg\r\nContent-Length: ' + str(len(frame)).encode() + b'\r\n\r\n' + frame + b'\r\n'
            await asyncio.sleep(.08)
    return StreamingResponse(frames(), media_type='multipart/x-mixed-replace; boundary=frame', headers={'Cache-Control': 'no-store'})


@app.websocket('/ws')
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        await websocket.send_json({'type': 'status', 'data': monitor.status()})
        while True:
            try:
                data = await websocket.receive_json()
                if not isinstance(data, dict):
                    raise ValueError('Expected a command object.')
                if data.get('type') == 'start_monitoring':
                    result = await asyncio.to_thread(start_monitoring, data.get('source', 'demo'))
                    await websocket.send_json({'type': 'status', 'data': result})
                elif data.get('type') == 'stop_monitoring':
                    result = await asyncio.to_thread(monitor.stop)
                    await websocket.send_json({'type': 'status', 'data': result})
                elif data.get('type') == 'ping':
                    await websocket.send_json({'type': 'pong'})
                else:
                    raise ValueError('Unknown command.')
            except (ValueError, HTTPException) as error:
                await websocket.send_json({'type': 'error', 'message': error.detail if isinstance(error, HTTPException) else str(error)})
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(websocket)
