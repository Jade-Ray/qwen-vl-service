import base64
import io
import re

from PIL import Image


DATA_URL_PATTERN = re.compile(r"^data:(?P<mime>image/[-+\w.]+);base64,(?P<data>.+)$", re.IGNORECASE | re.DOTALL)


def decode_base64_image(image_base64: str) -> tuple[Image.Image, str, str]:
    payload = image_base64.strip()
    mime_type = ""  # will be inferred from image.format when no data URL prefix
    match = DATA_URL_PATTERN.match(payload)
    if match:
        mime_type = match.group("mime").lower()
        payload = match.group("data")

    try:
        image_bytes = base64.b64decode(payload, validate=True)
    except Exception as exc:  # noqa: BLE001
        raise ValueError("image_base64 is not a valid base64 image payload.") from exc

    try:
        image = Image.open(io.BytesIO(image_bytes))
        image.load()
    except Exception as exc:  # noqa: BLE001
        raise ValueError("image_base64 could not be decoded into an image.") from exc

    normalized_base64 = base64.b64encode(image_bytes).decode("utf-8")
    source_format = _mime_to_format(mime_type, fallback=image.format)
    return image, source_format, normalized_base64


def encode_image_to_base64(image: Image.Image, preferred_format: str | None = None) -> tuple[str, str]:
    output_format = preferred_format or (image.format or "PNG")
    output_format = output_format.upper()
    save_image = image
    if output_format in {"JPEG", "JPG"}:
        output_format = "JPEG"
        if image.mode not in {"RGB", "L"}:
            save_image = image.convert("RGB")

    buffer = io.BytesIO()
    save_image.save(buffer, format=output_format)
    encoded = base64.b64encode(buffer.getvalue()).decode("utf-8")
    return encoded, output_format


def _mime_to_format(mime_type: str, fallback: str | None) -> str:
    if mime_type.endswith("jpeg") or mime_type.endswith("jpg"):
        return "JPEG"
    if mime_type.endswith("png"):
        return "PNG"
    if mime_type.endswith("webp"):
        return "WEBP"
    return (fallback or "PNG").upper()
