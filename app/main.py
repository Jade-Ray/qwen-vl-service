import json
import logging
import threading
import time
import uuid
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Request

from app.schemas import (
    DetectResponse,
    EchoImageRequest,
    EchoImageResponse,
    ImageDetectRequest,
)
from app.services.qwen_client import QwenClientError, QwenVLClient
from app.services.renderer import render_detections
from app.utils.config import Settings, get_settings
from app.utils.image_codec import decode_base64_image, encode_image_to_base64

# ---------------------------------------------------------------------------
# Structured JSON logging
# ---------------------------------------------------------------------------

class _JsonFormatter(logging.Formatter):
    _SKIP = frozenset({
        "name", "msg", "args", "created", "relativeCreated", "thread",
        "threadName", "processName", "process", "msecs", "taskName",
        "pathname", "filename", "module", "funcName", "lineno",
        "exc_info", "exc_text", "stack_info", "levelno", "message",
    })

    def format(self, record: logging.LogRecord) -> str:
        data: dict = {
            "time": self.formatTime(record, datefmt="%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "msg": record.getMessage(),
        }
        for key, val in vars(record).items():
            if key not in self._SKIP and key not in data:
                data[key] = val
        if record.exc_info:
            data["exc"] = self.formatException(record.exc_info)
        return json.dumps(data, ensure_ascii=False, default=str)


def _setup_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(_JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)


logger = logging.getLogger("qwen_detect")

# ---------------------------------------------------------------------------
# Concurrency guard (single detection at a time, process-scoped)
# ---------------------------------------------------------------------------

_detect_lock = threading.Semaphore(1)

# ---------------------------------------------------------------------------
# Application lifecycle
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    _setup_logging()
    settings = get_settings()
    if not settings.api_key:
        logger.warning("QWEN_API_KEY not set — /v1/detect will return 503 at runtime.")
        app.state.qwen_client = None
    else:
        app.state.qwen_client = QwenVLClient(settings)
        logger.info("Service started", extra={"model": settings.model})
    yield
    app.state.qwen_client = None
    logger.info("Service stopped")


app = FastAPI(
    title="Qwen-VL Detection Service",
    version="0.3.0",
    description="Receive base64 images, call Qwen-VL for detection, return rendered results.",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# Request logging middleware
# ---------------------------------------------------------------------------

@app.middleware("http")
async def _log_requests(request: Request, call_next):
    request_id = uuid.uuid4().hex[:8]
    start = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = round((time.perf_counter() - start) * 1000)
    logger.info(
        "request",
        extra={
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "elapsed_ms": elapsed_ms,
        },
    )
    return response

# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------

def get_qwen_client(request: Request) -> QwenVLClient:
    client = getattr(request.app.state, "qwen_client", None)
    if client is None:
        raise HTTPException(status_code=503, detail="Qwen API key not configured.")
    return client


def verify_api_key(
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
    settings: Settings = Depends(get_settings),
) -> None:
    """Validate inbound API key. Disabled when SERVICE_API_KEY is not set."""
    if settings.service_api_key and x_api_key != settings.service_api_key:
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key header.")

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health", summary="Health check")
def health() -> dict[str, str]:
    return {"status": "ok"}


v1 = APIRouter(prefix="/v1", dependencies=[Depends(verify_api_key)])


@v1.post(
    "/debug/echo-image",
    response_model=EchoImageResponse,
    summary="Echo image (debug)",
    description="Decode and re-encode the supplied image to verify base64 transport.",
)
def echo_image(
    request: EchoImageRequest,
    settings: Settings = Depends(get_settings),
) -> EchoImageResponse:
    try:
        image, source_format, _ = decode_base64_image(
            request.image_base64,
            max_b64_chars=settings.max_image_b64_chars,
            max_image_pixels=settings.max_image_pixels,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    rendered_base64, output_format = encode_image_to_base64(image, preferred_format=source_format)
    return EchoImageResponse(
        image_base64=rendered_base64,
        image_width=image.width,
        image_height=image.height,
        mime_type=f"image/{output_format.lower()}",
    )


@v1.post(
    "/detect",
    response_model=DetectResponse,
    summary="Object detection",
    description=(
        "Detect objects in the supplied image using Qwen-VL. "
        "Returns `type=detected` with bounding boxes when objects are found, "
        "or `type=no_detection` when none are found. "
        "Only one request is processed at a time; concurrent callers receive 503."
    ),
    responses={
        200: {"description": "Detection result (detected or no_detection)"},
        401: {"description": "Invalid or missing X-API-Key"},
        422: {"description": "Missing or malformed image"},
        502: {"description": "Upstream Qwen-VL error"},
        503: {"description": "Service busy or Qwen API key not configured"},
    },
)
def detect(
    request: ImageDetectRequest,
    qwen_client: QwenVLClient = Depends(get_qwen_client),
    settings: Settings = Depends(get_settings),
) -> DetectResponse:
    try:
        image, source_format, normalized_image_base64 = decode_base64_image(
            request.image_base64,
            max_b64_chars=settings.max_image_b64_chars,
            max_image_pixels=settings.max_image_pixels,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if not _detect_lock.acquire(blocking=False):
        raise HTTPException(status_code=503, detail="当前服务忙，请稍后再试。")

    try:
        try:
            detection_result = qwen_client.detect_objects(
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


app.include_router(v1)
