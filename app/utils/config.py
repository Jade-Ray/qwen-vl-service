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
    max_tokens: int = 1024


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        api_key=os.getenv("QWEN_API_KEY"),
        base_url=os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        model=os.getenv("QWEN_MODEL", "qwen3.5-omni-flash"),
        max_tokens=int(os.getenv("QWEN_MAX_TOKENS", "1024")),
    )
