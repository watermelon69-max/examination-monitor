"""Download the official Ultralytics detection and pose weights once."""
import os
from pathlib import Path

root = Path(__file__).resolve().parent
os.environ.setdefault('YOLO_CONFIG_DIR', str(root / '.cache/ultralytics'))

if __name__ == '__main__':
    from ultralytics import YOLO
    (root / 'models').mkdir(exist_ok=True)
    for name in ('yolov8n.pt', 'yolov8n-pose.pt'):
        path = root / 'models' / name
        print(f'Preparing {path}', flush=True)
        YOLO(str(path))
    print('Detection and head-landmark models are ready.', flush=True)

