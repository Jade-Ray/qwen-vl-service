"""API endpoint tests using FastAPI TestClient with mocked QwenVLClient."""
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.main import _detect_lock, get_qwen_client
from app.main import app
from app.schemas import DetectionObject, DetectionResult
from app.utils.config import Settings, get_settings
from tests.conftest import make_jpeg_base64, make_png_base64


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_client(objects: list[DetectionObject]) -> MagicMock:
    mock = MagicMock()
    mock.detect_objects.return_value = DetectionResult(objects=objects)
    return mock


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_lock() -> None:
    """Ensure semaphore is released before every test."""
    _detect_lock.acquire(blocking=False)
    _detect_lock.release()


@pytest.fixture(autouse=True)
def clear_dep_overrides():
    """Remove all dependency overrides after each test."""
    yield
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------

class TestHealthEndpoint:
    def test_health_returns_ok(self, api_client: TestClient) -> None:
        response = api_client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_health_no_auth_required(self, api_client: TestClient) -> None:
        response = api_client.get("/health")
        assert response.status_code != 401


# ---------------------------------------------------------------------------
# /v1/debug/echo-image
# ---------------------------------------------------------------------------

class TestEchoImageEndpoint:
    def test_echo_valid_png(self, api_client: TestClient) -> None:
        b64 = make_png_base64(50, 40)
        response = api_client.post("/v1/debug/echo-image", json={"image_base64": b64})
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["image_width"] == 50
        assert data["image_height"] == 40
        assert data["mime_type"] == "image/png"
        assert len(data["image_base64"]) > 0

    def test_echo_valid_jpeg(self, api_client: TestClient) -> None:
        b64 = make_jpeg_base64(60, 50)
        response = api_client.post("/v1/debug/echo-image", json={"image_base64": b64})
        assert response.status_code == 200
        assert response.json()["mime_type"] == "image/jpeg"

    def test_echo_with_data_url_prefix(self, api_client: TestClient) -> None:
        b64 = make_png_base64()
        data_url = f"data:image/png;base64,{b64}"
        response = api_client.post("/v1/debug/echo-image", json={"image_base64": data_url})
        assert response.status_code == 200

    def test_echo_missing_field_returns_422(self, api_client: TestClient) -> None:
        response = api_client.post("/v1/debug/echo-image", json={})
        assert response.status_code == 422

    def test_echo_invalid_base64_returns_422(self, api_client: TestClient) -> None:
        response = api_client.post("/v1/debug/echo-image", json={"image_base64": "not-valid!!!"})
        assert response.status_code == 422

    def test_echo_not_an_image_returns_422(self, api_client: TestClient) -> None:
        import base64
        garbage = base64.b64encode(b"hello world").decode()
        response = api_client.post("/v1/debug/echo-image", json={"image_base64": garbage})
        assert response.status_code == 422

    def test_echo_image_too_large_returns_422(self, api_client: TestClient) -> None:
        b64 = make_png_base64()
        # Override settings to set a tiny limit
        app.dependency_overrides[get_settings] = lambda: Settings(
            api_key="fake",
            base_url="http://x",
            model="m",
            max_tokens=1,
            qwen_timeout=10.0,
            qwen_max_retries=0,
            max_image_b64_chars=10,   # way too small
            max_image_pixels=0,
            service_api_key=None,
            service_port=8000,
        )
        response = api_client.post("/v1/debug/echo-image", json={"image_base64": b64})
        assert response.status_code == 422
        assert "too large" in response.json()["detail"].lower()

    def test_echo_image_too_many_pixels_returns_422(self, api_client: TestClient) -> None:
        b64 = make_png_base64(200, 200)
        app.dependency_overrides[get_settings] = lambda: Settings(
            api_key="fake",
            base_url="http://x",
            model="m",
            max_tokens=1,
            qwen_timeout=10.0,
            qwen_max_retries=0,
            max_image_b64_chars=0,
            max_image_pixels=100,  # 200×200=40000 > 100
            service_api_key=None,
            service_port=8000,
        )
        response = api_client.post("/v1/debug/echo-image", json={"image_base64": b64})
        assert response.status_code == 422
        assert "pixel" in response.json()["detail"].lower()


# ---------------------------------------------------------------------------
# /v1/detect
# ---------------------------------------------------------------------------

class TestDetectEndpoint:
    def test_detect_missing_image_returns_422(self, api_client: TestClient) -> None:
        response = api_client.post("/v1/detect", json={})
        assert response.status_code == 422

    def test_detect_invalid_image_returns_422(self, api_client: TestClient) -> None:
        response = api_client.post("/v1/detect", json={"image_base64": "bad!!!"})
        assert response.status_code == 422

    def test_detect_no_objects_returns_no_detection(self, api_client: TestClient) -> None:
        b64 = make_png_base64()
        app.dependency_overrides[get_qwen_client] = lambda: _mock_client([])
        response = api_client.post("/v1/detect", json={"image_base64": b64})
        assert response.status_code == 200
        data = response.json()
        assert data["type"] == "no_detection"
        assert data.get("objects") is None
        assert data.get("image_base64") is None

    def test_detect_with_objects_returns_detected(self, api_client: TestClient) -> None:
        b64 = make_png_base64(200, 150)
        objs = [DetectionObject(label="car", bbox_2d=[10, 10, 100, 80])]
        app.dependency_overrides[get_qwen_client] = lambda: _mock_client(objs)
        response = api_client.post("/v1/detect", json={"image_base64": b64})
        assert response.status_code == 200
        data = response.json()
        assert data["type"] == "detected"
        assert len(data["objects"]) == 1
        assert data["objects"][0]["label"] == "car"
        assert data["objects"][0]["bbox_2d"] == [10, 10, 100, 80]
        assert data["image_width"] == 200
        assert data["image_height"] == 150
        assert len(data["image_base64"]) > 0

    def test_detect_without_prompt_passes_none(self, api_client: TestClient) -> None:
        b64 = make_png_base64()
        mock = _mock_client([])
        app.dependency_overrides[get_qwen_client] = lambda: mock
        api_client.post("/v1/detect", json={"image_base64": b64})
        assert mock.detect_objects.call_args.kwargs.get("prompt") is None

    def test_detect_with_prompt_passes_through(self, api_client: TestClient) -> None:
        b64 = make_png_base64()
        mock = _mock_client([])
        app.dependency_overrides[get_qwen_client] = lambda: mock
        api_client.post("/v1/detect", json={"image_base64": b64, "prompt": "find cats"})
        assert mock.detect_objects.call_args.kwargs.get("prompt") == "find cats"

    def test_detect_qwen_error_returns_502(self, api_client: TestClient) -> None:
        from app.services.qwen_client import QwenClientError
        b64 = make_png_base64()
        mock = MagicMock()
        mock.detect_objects.side_effect = QwenClientError("upstream down")
        app.dependency_overrides[get_qwen_client] = lambda: mock
        response = api_client.post("/v1/detect", json={"image_base64": b64})
        assert response.status_code == 502
        assert "upstream down" in response.json()["detail"]

    def test_detect_busy_returns_503(self, api_client: TestClient) -> None:
        b64 = make_png_base64()
        _detect_lock.acquire(blocking=False)
        try:
            response = api_client.post("/v1/detect", json={"image_base64": b64})
        finally:
            _detect_lock.release()
        assert response.status_code == 503
        assert "服务忙" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

class TestAuthentication:
    def _settings_with_auth(self) -> Settings:
        return Settings(
            api_key="fake",
            base_url="http://x",
            model="m",
            max_tokens=1,
            qwen_timeout=10.0,
            qwen_max_retries=0,
            max_image_b64_chars=0,
            max_image_pixels=0,
            service_api_key="secret-key",
            service_port=8000,
        )

    def test_auth_disabled_no_header_passes(self, api_client: TestClient) -> None:
        b64 = make_png_base64()
        app.dependency_overrides[get_qwen_client] = lambda: _mock_client([])
        response = api_client.post("/v1/detect", json={"image_base64": b64})
        assert response.status_code != 401

    def test_auth_enabled_wrong_key_returns_401(self, api_client: TestClient) -> None:
        app.dependency_overrides[get_settings] = self._settings_with_auth
        app.dependency_overrides[get_qwen_client] = lambda: _mock_client([])
        response = api_client.post(
            "/v1/detect",
            json={"image_base64": make_png_base64()},
            headers={"X-API-Key": "wrong"},
        )
        assert response.status_code == 401

    def test_auth_enabled_no_header_returns_401(self, api_client: TestClient) -> None:
        app.dependency_overrides[get_settings] = self._settings_with_auth
        response = api_client.post("/v1/detect", json={"image_base64": make_png_base64()})
        assert response.status_code == 401

    def test_auth_enabled_correct_key_passes(self, api_client: TestClient) -> None:
        app.dependency_overrides[get_settings] = self._settings_with_auth
        app.dependency_overrides[get_qwen_client] = lambda: _mock_client([])
        response = api_client.post(
            "/v1/detect",
            json={"image_base64": make_png_base64()},
            headers={"X-API-Key": "secret-key"},
        )
        assert response.status_code == 200

    def test_health_always_public(self, api_client: TestClient) -> None:
        app.dependency_overrides[get_settings] = self._settings_with_auth
        response = api_client.get("/health")
        assert response.status_code == 200
