import cv2
import numpy as np

class Visualizer:
    def __init__(self):
        self.state_colors = {
            'NORMAL': (0, 255, 0),      # Green
            'OBSERVE': (0, 255, 255),   # Yellow
            'SUSPICIOUS': (0, 165, 255), # Orange
            'ALERT': (0, 0, 255),       # Red
        }
    
    def draw_bbox(self, frame, bbox, track_id, state='NORMAL', risk_score=0, label_info=None):
        x1, y1, x2, y2 = map(int, bbox)
        color = self.state_colors.get(state, (255, 255, 255))
        
        # Draw bounding box
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        
        # Draw label background
        label = f"ID:{track_id} | {state} | R:{risk_score:.1f}"
        if label_info:
            label = f"{label} | {label_info}"
        
        (w, h), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        cv2.rectangle(frame, (x1, y1 - h - 10), (x1 + w + 5, y1), color, -1)
        cv2.putText(frame, label, (x1 + 2, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 
                    0.5, (255, 255, 255), 1)
        
        return frame
    
    def draw_seat(self, frame, seat_id, bbox, is_occupied=False):
        x1, y1, x2, y2 = map(int, bbox)
        color = (255, 0, 255) if not is_occupied else (128, 0, 128)
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 1)
        cv2.putText(frame, f"Seat {seat_id}", (x1 + 2, y1 - 2), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1)
        return frame
    
    def draw_alert_overlay(self, frame, alerts):
        if not alerts:
            return frame
        # Draw alert banner
        overlay = frame.copy()
        cv2.rectangle(overlay, (0, 0), (frame.shape[1], 60), (0, 0, 255), -1)
        cv2.addWeighted(overlay, 0.7, frame, 0.3, 0, frame)
        alert_text = f"⚠ {len(alerts)} ACTIVE ALERTS"
        cv2.putText(frame, alert_text, (10, 35), cv2.FONT_HERSHEY_SIMPLEX, 
                    1, (255, 255, 255), 2)
        return frame
