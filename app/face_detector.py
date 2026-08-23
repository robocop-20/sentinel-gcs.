"""Detection-only OpenCV YuNet ONNX adapter.

YuNet reports a face bounding box, five landmarks, and detector confidence.
This module deliberately has no embeddings, identity, gallery, search, or
matching capability.
"""

from pathlib import Path
import cv2
from .schemas import BBox, FaceDetection


class FaceDetector:
    def __init__(
        self, model_path: str, confidence: float, max_dimension_px: int = 640
    ) -> None:
        if not model_path or not Path(model_path).is_file():
            raise ValueError(
                "FACE_DETECTOR_MODEL_PATH must point to the local YuNet ONNX model."
            )
        self.detector = cv2.FaceDetectorYN.create(
            model=model_path,
            config="",
            input_size=(320, 320),
            score_threshold=confidence,
            nms_threshold=0.3,
            top_k=5000,
        )
        self.max_dimension_px = max(int(max_dimension_px), 160)

    def detect(self, frame) -> list[FaceDetection]:
        height, width = frame.shape[:2]
        scale = min(1.0, self.max_dimension_px / max(height, width))
        if scale < 1.0:
            input_frame = cv2.resize(
                frame,
                (max(1, round(width * scale)), max(1, round(height * scale))),
                interpolation=cv2.INTER_AREA,
            )
        else:
            input_frame = frame
        input_height, input_width = input_frame.shape[:2]
        self.detector.setInputSize((input_width, input_height))
        _, result = self.detector.detect(input_frame)
        if result is None:
            return []
        faces: list[FaceDetection] = []
        for row in result:
            x, y, box_width, box_height = (float(value) / scale for value in row[:4])
            landmarks = [
                (float(row[index]) / scale, float(row[index + 1]) / scale)
                for index in range(4, 14, 2)
            ]
            faces.append(
                FaceDetection(
                    confidence=float(row[14]),
                    bbox=BBox(x=x, y=y, width=box_width, height=box_height),
                    landmarks=landmarks,
                )
            )
        return faces


def blur_faces(frame, faces: list[FaceDetection]) -> None:
    """Blur every detected face before preview or export encoding."""
    for face in faces:
        x, y, width, height = map(
            int, (face.bbox.x, face.bbox.y, face.bbox.width, face.bbox.height)
        )
        roi = frame[max(y, 0) : max(y + height, 0), max(x, 0) : max(x + width, 0)]
        if roi.size:
            roi[:] = cv2.GaussianBlur(roi, (31, 31), 0)
