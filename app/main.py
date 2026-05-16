import threading

from fastapi import FastAPI, HTTPException

from app.schemas import (
    DetectResponse,
    EchoImageRequest,
    EchoImageResponse,
    ImageDetectRequest,
)
from app.services.qwen_client import QwenClientError, QwenVLClient
from app.services.renderer import render_detections
from app.utils.image_codec import decode_base64_image, encode_image_to_base64

app = FastAPI(
    title="Qwen-VL Detection Service",
    version="0.2.0",
    description="Receive base64 images, call Qwen-VL for detection, and return rendered base64 images.",
)

# Only one concurrent detection request is allowed (model inference is slow).
_detect_lock = threading.Semaphore(1)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/debug/echo-image", response_model=EchoImageResponse)
def echo_image(request: EchoImageRequest) -> EchoImageResponse:
    try:
        image, source_format, _ = decode_base64_image(request.image_base64)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    rendered_base64, output_format = encode_image_to_base64(image, preferred_format=source_format)
    return EchoImageResponse(
        image_base64=rendered_base64,
        image_width=image.width,
        image_height=image.height,
        mime_type=f"image/{output_format.lower()}",
    )


@app.post("/detect", response_model=DetectResponse)
def detect(request: ImageDetectRequest) -> DetectResponse:
    # Validate image first — cheap and returns 422 immediately on bad input.
    try:
        image, source_format, normalized_image_base64 = decode_base64_image(request.image_base64)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # Reject if another detection is already in progress.
    if not _detect_lock.acquire(blocking=False):
        raise HTTPException(status_code=503, detail="当前服务忙，请稍后再试。")

    try:
        try:
            detection_result = QwenVLClient().detect_objects(
                image_base64=normalized_image_base64,
                image_mime=f"image/{source_format.lower()}",
                prompt=request.prompt,
                image_width=image.width,
                image_height=image.height,
            )
        except QwenClientError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        _detect_lock.release()

    if not detection_result.objects:
        return DetectResponse(type="no_detection")

    rendered_image = render_detections(image, detection_result.objects)
    rendered_base64, output_format = encode_image_to_base64(rendered_image, preferred_format=source_format)

    return DetectResponse(
        type="detected",
        objects=detection_result.objects,
        image_base64=rendered_base64,
        image_width=image.width,
        image_height=image.height,
        mime_type=f"image/{output_format.lower()}",
    )
