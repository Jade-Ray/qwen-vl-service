import base64
import io
import os

# Set env vars before any app module is imported so lru_cache reads them correctly
os.environ.setdefault("QWEN_API_KEY", "test-fake-key")
os.environ.setdefault("SERVICE_API_KEY", "")  # auth disabled in tests

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.utils.config import get_settings


def make_png_base64(width: int = 100, height: int = 80, color: tuple = (255, 128, 0)) -> str:
    img = Image.new("RGB", (width, height), color=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def make_jpeg_base64(width: int = 100, height: int = 80) -> str:
    img = Image.new("RGB", (width, height), color=(0, 128, 255))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()


@pytest.fixture(scope="session")
def api_client():
    """Session-scoped TestClient that runs the app lifespan."""
    # Clear settings cache so the env vars set above take effect
    get_settings.cache_clear()
    from app.main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture
def png_b64() -> str:
    return make_png_base64()


@pytest.fixture
def jpeg_b64() -> str:
    return make_jpeg_base64()


@pytest.fixture
def png_data_url(png_b64: str) -> str:
    return f"data:image/png;base64,{png_b64}"
