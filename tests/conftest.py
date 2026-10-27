import os
from pathlib import Path
from uuid import uuid4

# Keep test sessions, video uploads and evidence separate from the user's data.
TEST_DATA = Path(__file__).resolve().parents[1] / 'artifacts' / ('test-data-' + uuid4().hex)
TEST_DATA.mkdir(parents=True)
os.environ['EXAM_DATA_DIR'] = str(TEST_DATA)
os.environ['YOLO_CONFIG_DIR'] = str(Path(__file__).resolve().parents[1] / '.cache/ultralytics')
