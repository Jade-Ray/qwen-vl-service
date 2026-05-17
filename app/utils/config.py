import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the project root if present.
# Variables already set in the shell take precedence (override=False).
_env_path = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(dotenv_path=_env_path, override=False)


@dataclass(frozen=True)
class Settings:
    api_key: str | None
    base_url: str
    model: str
    max_tokens: int
    # Qwen API request timeout in seconds (0 = library default)
    qwen_timeout: float
    # Max retry attempts on transient errors (0 = no retry)
    qwen_max_retries: int
    # Input limits (0 = unlimited)
    max_image_b64_chars: int
    max_image_pixels: int
    # Service-level API key for inbound auth (None = auth disabled)
    service_api_key: str | None
    # Port the uvicorn server listens on
    service_port: int


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        api_key=os.getenv("QWEN_API_KEY"),
        base_url=os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        model=os.getenv("QWEN_MODEL", "qwen-vl-max"),
        max_tokens=int(os.getenv("QWEN_MAX_TOKENS", "1024")),
        qwen_timeout=float(os.getenv("QWEN_TIMEOUT", "120.0")),
        qwen_max_retries=int(os.getenv("QWEN_MAX_RETRIES", "2")),
        # ~15 MB image ≈ 20 MB base64
        max_image_b64_chars=int(os.getenv("MAX_IMAGE_B64_CHARS", str(20 * 1024 * 1024))),
        # 4096×4096 default
        max_image_pixels=int(os.getenv("MAX_IMAGE_PIXELS", str(4096 * 4096))),
        service_api_key=os.getenv("SERVICE_API_KEY") or None,
        service_port=int(os.getenv("SERVICE_PORT", "8000")),
    )
