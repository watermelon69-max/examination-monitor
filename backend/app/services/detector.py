import os
import math
from pathlib import Path
from app.core.config import config
from app.services.tracker import intersection_over_union


class PersonDetector:
    def __init__(self):
        os.environ.setdefault('YOLO_CONFIG_DIR', str(config.project_root / '.cache/ultralytics'))
        from ultralytics import YOLO
        self.device = config.get('detection.device', 'cpu')
        self.conf_threshold = config.get('detection.confidence_threshold', 0.5)
        self.phone_threshold = config.get('events.mobile_phone.confidence_threshold', 0.4)
        self.iou_threshold = config.get('detection.iou_threshold', 0.45)
        self.model = YOLO(str(config.project_root / 'models' / config.get('detection.model', 'yolov8n.pt')))
        self.pose = None
        if config.get('detection.pose_enabled', True):
            self.pose = YOLO(str(config.project_root / 'models' / config.get('detection.pose_model', 'yolov8n-pose.pt')))

    def analyze(self, frame):
        result = self.model.predict(frame, conf=min(self.conf_threshold, self.phone_threshold), iou=self.iou_threshold, classes=[0, 67], device=self.device, imgsz=config.get('detection.image_size', 640), verbose=False)[0]
        persons, phones = [], []
        for box, confidence, class_id in zip(result.boxes.xyxy.cpu().tolist(), result.boxes.conf.cpu().tolist(), result.boxes.cls.cpu().tolist()):
            item = {'bbox': box, 'conf': confidence}
            if int(class_id) == 0 and confidence >= self.conf_threshold:
                persons.append(item)
            elif int(class_id) == 67 and confidence >= self.phone_threshold:
                phones.append(item)
        if self.pose is not None and persons:
            pose_result = self.pose.predict(frame, conf=self.conf_threshold, device=self.device, imgsz=config.get('detection.image_size', 640), verbose=False)[0]
            if pose_result.keypoints is not None:
                pose_boxes = pose_result.boxes.xyxy.cpu().tolist()
                points = pose_result.keypoints.xy.cpu().tolist()
                confidences = pose_result.keypoints.conf.cpu().tolist()
                for person in persons:
                    matches = [(intersection_over_union(person['bbox'], box), index) for index, box in enumerate(pose_boxes)]
                    overlap, index = max(matches, default=(0, 0))
                    if overlap < 0.3:
                        continue
                    point, confidence = points[index], confidences[index]
                    # Nose relative to visible ear landmarks gives a coarse orientation cue.
                    # Skip obscured heads rather than infer gaze from body movement.
                    if min(confidence[0], confidence[3], confidence[4]) > 0.35:
                        ear_span = abs(point[3][0] - point[4][0])
                        if ear_span > 4:
                            offset = point[0][0] - (point[3][0] + point[4][0]) / 2
                            person['head_yaw'] = math.degrees(math.atan2(offset, ear_span / 2))
        return persons, phones

    def detect(self, frame):
        return self.analyze(frame)[0]
