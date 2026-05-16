"""API endpoint tests using FastAPI TestClient with mocked QwenVLClient."""
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app, _detect_lock
from app.schemas import DetectionObject, DetectionResult
from tests.conftest import make_png_base64, make_jpeg_base64

client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_lock() -> None:
    """Ensure the semaphore is always released between tests."""
    # Drain any leftover acquisitions from a failed test
    while not _detect_lock.acquire(blocking=False):  # pragma: no cover
        pass
    _detect_lock.release()


class TestHealthEndpoint:
    def test_health_returns_ok(self) -> None:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestEchoImageEndpoint:
    def test_echo_valid_png(self) -> None:
        b64 = make_png_base64(50, 40)
        response = client.post("/debug/echo-image", json={"image_base64": b64})
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["image_width"] == 50
        assert data["image_height"] == 40
        assert data["mime_type"] == "image/png"
        assert len(data["image_base64"]) > 0

    def test_echo_valid_jpeg(self) -> None:
        b64 = make_jpeg_base64(60, 50)
        response = client.post("/debug/echo-image", json={"image_base64": b64})
        assert response.status_code == 200
        assert response.json()["mime_type"] == "image/jpeg"

    def test_echo_with_data_url_prefix(self) -> None:
        b64 = make_png_base64()
        data_url = f"data:image/png;base64,{b64}"
        response = client.post("/debug/echo-image", json={"image_base64": data_url})
        assert response.status_code == 200

    def test_echo_missing_field_returns_422(self) -> None:
        response = client.post("/debug/echo-image", json={})
        assert response.status_code == 422

    def test_echo_invalid_base64_returns_422(self) -> None:
        response = client.post("/debug/echo-image", json={"image_base64": "not-valid!!!"})
        assert response.status_code == 422

    def test_echo_not_an_image_returns_422(self) -> None:
        import base64
        garbage = base64.b64encode(b"hello world").decode()
        response = client.post("/debug/echo-image", json={"image_base64": garbage})
        assert response.status_code == 422


class TestDetectEndpoint:
    def _mock_client(self, objects: list[DetectionObject]) -> MagicMock:
        mock_instance = MagicMock()
        mock_instance.detect_objects.return_value = DetectionResult(objects=objects)
        return mock_instance

    def test_detect_missing_image_returns_422(self) -> None:
        response = client.post("/detect", json={})
        assert response.status_code == 422

    def test_detect_invalid_image_returns_422(self) -> None:
        response = client.post("/detect", json={"image_base64": "bad!!!"})
        assert response.status_code == 422

    def test_detect_no_objects_returns_no_detection(self) -> None:
        b64 = make_png_base64()
        with patch("app.main.QwenVLClient", return_value=self._mock_client([])):
            response = client.post("/detect", json={"image_base64": b64})
        assert response.status_code == 200
        data = response.json()
        assert data["type"] == "no_detection"
        assert data.get("objects") is None
        assert data.get("image_base64") is None

    def test_detect_with_objects_returns_detected(self) -> None:
        b64 = make_png_base64(200, 150)
        objs = [DetectionObject(label="car", bbox_2d=[10, 10, 100, 80])]
        with patch("app.main.QwenVLClient", return_value=self._mock_client(objs)):
            response = client.post("/detect", json={"image_base64": b64})
        assert response.status_code == 200
        data = response.json()
        assert data["type"] == "detected"
        assert len(data["objects"]) == 1
        assert data["objects"][0]["label"] == "car"
        assert data["objects"][0]["bbox_2d"] == [10, 10, 100, 80]
        assert data["image_width"] == 200
        assert data["image_height"] == 150
        assert len(data["image_base64"]) > 0

    def test_detect_without_prompt_uses_default(self) -> None:
        b64 = make_png_base64()
        mock_instance = self._mock_client([])
        with patch("app.main.QwenVLClient", return_value=mock_instance):
            client.post("/detect", json={"image_base64": b64})
        call_kwargs = mock_instance.detect_objects.call_args.kwargs
        assert call_kwargs.get("prompt") is None

    def test_detect_with_prompt_passes_through(self) -> None:
        b64 = make_png_base64()
        mock_instance = self._mock_client([])
        with patch("app.main.QwenVLClient", return_value=mock_instance):
            client.post("/detect", json={"image_base64": b64, "prompt": "find cats"})
        call_kwargs = mock_instance.detect_objects.call_args.kwargs
        assert call_kwargs.get("prompt") == "find cats"

    def test_detect_qwen_error_returns_502(self) -> None:
        from app.services.qwen_client import QwenClientError
        b64 = make_png_base64()
        mock_instance = MagicMock()
        mock_instance.detect_objects.side_effect = QwenClientError("upstream down")
        with patch("app.main.QwenVLClient", return_value=mock_instance):
            response = client.post("/detect", json={"image_base64": b64})
        assert response.status_code == 502
        assert "upstream down" in response.json()["detail"]

    def test_detect_busy_returns_503(self) -> None:
        b64 = make_png_base64()
        # Manually acquire the lock to simulate a busy service
        _detect_lock.acquire(blocking=False)
        try:
            response = client.post("/detect", json={"image_base64": b64})
        finally:
            _detect_lock.release()
        assert response.status_code == 503
        assert "服务忙" in response.json()["detail"]
