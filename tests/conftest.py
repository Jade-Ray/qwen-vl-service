import base64
import io

import pytest
from PIL import Image


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


@pytest.fixture
def png_b64() -> str:
    return make_png_base64()


@pytest.fixture
def jpeg_b64() -> str:
    return make_jpeg_base64()


@pytest.fixture
def png_data_url(png_b64: str) -> str:
    return f"data:image/png;base64,{png_b64}"
