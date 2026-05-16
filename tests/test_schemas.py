import pytest
from pydantic import ValidationError

from app.schemas import (
    DetectResponse,
    DetectionObject,
    EchoImageRequest,
    ImageDetectRequest,
)


class TestDetectionObject:
    def test_valid_object(self) -> None:
        obj = DetectionObject(label="cat", bbox_2d=[10, 20, 100, 200])
        assert obj.label == "cat"
        assert obj.bbox_2d == [10, 20, 100, 200]
        assert obj.score is None

    def test_with_score(self) -> None:
        obj = DetectionObject(label="dog", bbox_2d=[0, 0, 50, 50], score=0.95)
        assert obj.score == pytest.approx(0.95)

    def test_invalid_bbox_length_raises(self) -> None:
        with pytest.raises(ValidationError):
            DetectionObject(label="cat", bbox_2d=[10, 20, 100])

    def test_empty_label_raises(self) -> None:
        with pytest.raises(ValidationError):
            DetectionObject(label="", bbox_2d=[0, 0, 10, 10])

    def test_score_out_of_range_raises(self) -> None:
        with pytest.raises(ValidationError):
            DetectionObject(label="x", bbox_2d=[0, 0, 1, 1], score=1.5)


class TestImageDetectRequest:
    def test_prompt_optional(self) -> None:
        req = ImageDetectRequest(image_base64="abc123")
        assert req.prompt is None

    def test_prompt_provided(self) -> None:
        req = ImageDetectRequest(image_base64="abc123", prompt="detect cars")
        assert req.prompt == "detect cars"

    def test_missing_image_base64_raises(self) -> None:
        with pytest.raises(ValidationError):
            ImageDetectRequest()  # type: ignore[call-arg]

    def test_empty_image_base64_raises(self) -> None:
        with pytest.raises(ValidationError):
            ImageDetectRequest(image_base64="")


class TestDetectResponse:
    def test_no_detection_response(self) -> None:
        resp = DetectResponse(type="no_detection")
        assert resp.type == "no_detection"
        assert resp.objects is None
        assert resp.image_base64 is None

    def test_detected_response(self) -> None:
        obj = DetectionObject(label="car", bbox_2d=[0, 0, 100, 100])
        resp = DetectResponse(
            type="detected",
            objects=[obj],
            image_base64="abc",
            image_width=640,
            image_height=480,
            mime_type="image/png",
        )
        assert resp.type == "detected"
        assert len(resp.objects) == 1  # type: ignore[arg-type]
        assert resp.objects[0].label == "car"  # type: ignore[index]
