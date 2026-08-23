"""Local second-model verification for marginal generic-person detections.

This is deliberately not a face model. It sees only the current local frame,
uses an independent COCO detector, and returns a bounded object-level result.
It cannot identify, compare, enrol, or re-identify a person.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

import cv2


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class PersonVerificationResult:
    verdict: str
    confidence: float | None = None
    iou: float | None = None


def _iou(
    first: tuple[float, float, float, float], second: tuple[float, float, float, float]
) -> float:
    x1 = max(first[0], second[0])
    y1 = max(first[1], second[1])
    x2 = min(first[2], second[2])
    y2 = min(first[3], second[3])
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    first_area = max(0.0, first[2] - first[0]) * max(0.0, first[3] - first[1])
    second_area = max(0.0, second[2] - second[0]) * max(0.0, second[3] - second[1])
    denominator = first_area + second_area - intersection
    return intersection / denominator if denominator else 0.0


class LocalPersonVerifier:
    """Independent local detector, cached once and throttled per ByteTrack ID."""

    method = "local_fasterrcnn_mobilenet"

    def __init__(self, settings) -> None:
        self.settings = settings
        self._cache: dict[str, tuple[float, PersonVerificationResult]] = {}
        self._available = False
        self._model = None
        self._torch = None
        try:
            Path(settings.person_verifier_cache_dir).mkdir(parents=True, exist_ok=True)
            os.environ.setdefault("TORCH_HOME", settings.person_verifier_cache_dir)
            import torch
            from torchvision.models.detection import (
                FasterRCNN_MobileNet_V3_Large_320_FPN_Weights,
                fasterrcnn_mobilenet_v3_large_320_fpn,
            )

            self._torch = torch
            self.device = (
                "cpu"
                if not settings.yolo_device
                or settings.yolo_device.lower() in {"cpu", "-1"}
                else f"cuda:{settings.yolo_device}"
            )
            if self.device.startswith("cuda") and not torch.cuda.is_available():
                self.device = "cpu"
            # TorchVision caches official pretrained weights below TORCH_HOME.
            self._model = (
                fasterrcnn_mobilenet_v3_large_320_fpn(
                    weights=FasterRCNN_MobileNet_V3_Large_320_FPN_Weights.DEFAULT,
                )
                .to(self.device)
                .eval()
            )
            self._available = True
            LOGGER.info(
                "Local person verifier ready",
                extra={"event": "model_loaded", "component": "person_verifier"},
            )
        except Exception:
            # Verification is a precision improvement, never a single point
            # of failure for the primary real-time detection path.
            LOGGER.warning(
                "Local person verifier unavailable",
                extra={
                    "event": "optional_model_unavailable",
                    "component": "person_verifier",
                },
            )

    @property
    def available(self) -> bool:
        return self._available

    def should_review(self, confidence: float) -> bool:
        return confidence < self.settings.person_verifier_max_yolo_confidence

    def verify(
        self,
        track_id: str,
        frame,
        yolo_bbox: tuple[float, float, float, float],
        observed_at: float,
    ) -> PersonVerificationResult:
        previous = self._cache.get(track_id)
        if previous and observed_at - previous[0] <= max(
            self.settings.person_verifier_cache_s, 0.1
        ):
            return previous[1]
        if not self.available or self._torch is None or self._model is None:
            return PersonVerificationResult("unavailable")
        try:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            image = (
                self._torch.from_numpy(rgb)
                .permute(2, 0, 1)
                .float()
                .div(255)
                .to(self.device)
            )
            with self._torch.inference_mode():
                prediction = self._model([image])[0]
            candidates = []
            for box, label, score in zip(
                prediction["boxes"].tolist(),
                prediction["labels"].tolist(),
                prediction["scores"].tolist(),
            ):
                if (
                    int(label) != 1
                    or float(score) < self.settings.person_verifier_detection_confidence
                ):
                    continue
                overlap = _iou(yolo_bbox, tuple(float(value) for value in box))
                candidates.append((float(score), overlap))
            best = max(candidates, key=lambda value: value[1], default=None)
            result = (
                PersonVerificationResult("confirmed", best[0], best[1])
                if best and best[1] >= self.settings.person_verifier_min_iou
                else PersonVerificationResult("contradicted")
            )
        except Exception:
            result = PersonVerificationResult("unavailable")
        self._cache[track_id] = (observed_at, result)
        self._cache = {
            key: value
            for key, value in self._cache.items()
            if observed_at - value[0]
            <= max(self.settings.person_verifier_cache_s, 0.1) * 3
        }
        return result
