"""Synthetic inputs for exercising the real tracking, rules, agent and storage."""
import math
import cv2
import numpy as np

WIDTH, HEIGHT = 960, 540
CENTERS = [(160, 175), (450, 175), (740, 175), (160, 410), (450, 410), (740, 410)]
SEATS = {index + 1: {'bbox': [x - 65, y - 75, x + 65, y + 75], 'center': [x, y]} for index, (x, y) in enumerate(CENTERS)}


def demo_frame(timestamp):
    frame = np.full((HEIGHT, WIDTH, 3), (28, 23, 17), dtype=np.uint8)
    cv2.putText(frame, 'SIMULATION / SYNTHETIC EXAM HALL', (24, 28), cv2.FONT_HERSHEY_SIMPLEX, .65, (160, 185, 190), 1)
    persons, phones = [], []
    phase = timestamp % 42
    for index, (base_x, base_y) in enumerate(CENTERS):
        x, y = float(base_x), float(base_y)
        if index in (0, 1, 2):
            # Leave separate seats and converge on the aisle for a sustained group.
            factor = min(1, max(0, (phase - 9) / 5)) if phase < 32 else max(0, 1 - (phase - 32) / 6)
            x += (450 + (index - 1) * 75 - x) * factor
            y += (285 - y) * factor
        if index == 5 and 10 < phase < 19:
            x += 75 * math.sin((phase - 10) * 5)
        color = (130, 155, 165)
        cv2.rectangle(frame, (base_x - 62, base_y - 70), (base_x + 62, base_y + 70), (65, 65, 45), 1)
        cv2.putText(frame, f'SEAT {index + 1}', (base_x - 30, base_y + 65), cv2.FONT_HERSHEY_SIMPLEX, .4, (130, 130, 100), 1)
        cv2.circle(frame, (int(x), int(y - 30)), 16, color, -1)
        cv2.ellipse(frame, (int(x), int(y + 10)), (27, 28), 0, 0, 360, color, -1)
        cv2.line(frame, (int(x - 12), int(y + 30)), (int(x - 18), int(y + 48)), color, 6)
        cv2.line(frame, (int(x + 12), int(y + 30)), (int(x + 18), int(y + 48)), color, 6)
        bbox = [x - 32, y - 50, x + 32, y + 50]
        person = {'bbox': bbox, 'conf': .95, 'head_yaw': 0}
        if index == 3:
            person['head_yaw'] = 45 * (1 if int(timestamp / .8) % 2 else -1)
        persons.append(person)
        if index == 4 and 3 < phase < 30:
            phone_box = [x + 9, y - 3, x + 22, y + 18]
            cv2.rectangle(frame, tuple(map(int, phone_box[:2])), tuple(map(int, phone_box[2:])), (180, 200, 95), -1)
            phones.append({'bbox': phone_box, 'conf': .94})
    return frame, persons, phones
