import base64
import io

import pytest
from PIL import Image

from app.utils.image_codec import decode_base64_image, encode_image_to_base64
from tests.conftest import make_png_base64, make_jpeg_base64


class TestDecodeBase64Image:
    def test_decode_valid_png(self, png_b64: str) -> None:
        image, fmt, normalized = decode_base64_image(png_b64)
        assert isinstance(image, Image.Image)
        assert fmt == "PNG"
        assert len(normalized) > 0

    def test_decode_valid_jpeg(self, jpeg_b64: str) -> None:
        image, fmt, normalized = decode_base64_image(jpeg_b64)
        assert isinstance(image, Image.Image)
        assert fmt == "JPEG"

    def test_decode_data_url_prefix(self, png_data_url: str) -> None:
        image, fmt, normalized = decode_base64_image(png_data_url)
        assert isinstance(image, Image.Image)
        assert fmt == "PNG"

    def test_decode_strips_whitespace(self, png_b64: str) -> None:
        image, fmt, _ = decode_base64_image(f"  {png_b64}  ")
        assert isinstance(image, Image.Image)

    def test_decode_invalid_base64_raises(self) -> None:
        with pytest.raises(ValueError, match="not a valid base64"):
            decode_base64_image("not!valid!base64!!!")

    def test_decode_valid_base64_but_not_image_raises(self) -> None:
        garbage = base64.b64encode(b"this is not an image").decode()
        with pytest.raises(ValueError, match="could not be decoded into an image"):
            decode_base64_image(garbage)

    def test_decode_empty_string_raises(self) -> None:
        with pytest.raises(ValueError):
            decode_base64_image("   ")


class TestEncodeImageToBase64:
    def test_encode_png_roundtrip(self) -> None:
        original = Image.new("RGB", (50, 40), color=(10, 20, 30))
        encoded, fmt = encode_image_to_base64(original, preferred_format="PNG")
        assert fmt == "PNG"
        decoded_bytes = base64.b64decode(encoded)
        recovered = Image.open(io.BytesIO(decoded_bytes))
        assert recovered.size == (50, 40)

    def test_encode_jpeg_converts_rgba(self) -> None:
        rgba_image = Image.new("RGBA", (30, 30), color=(255, 0, 0, 128))
        encoded, fmt = encode_image_to_base64(rgba_image, preferred_format="JPEG")
        assert fmt == "JPEG"
        assert len(encoded) > 0

    def test_encode_defaults_to_png(self) -> None:
        img = Image.new("RGB", (10, 10))
        _, fmt = encode_image_to_base64(img)
        assert fmt == "PNG"
