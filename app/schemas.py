from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class EchoImageRequest(BaseModel):
    image_base64: str = Field(..., min_length=1, description="Raw base64 or data URL image payload.")


class ImageDetectRequest(BaseModel):
    image_base64: str = Field(..., min_length=1, description="Raw base64 or data URL image payload.")
    prompt: str | None = Field(default=None, description="Detection instruction for Qwen-VL. Uses default if omitted.")


class DetectionObject(BaseModel):
    label: str = Field(..., min_length=1)
    bbox_2d: list[int] = Field(..., min_length=4, max_length=4)
    score: float | None = Field(default=None, ge=0.0, le=1.0)

    @field_validator("bbox_2d")
    @classmethod
    def validate_bbox(cls, bbox_2d: list[int]) -> list[int]:
        if len(bbox_2d) != 4:
            raise ValueError("bbox_2d must contain exactly 4 integer coordinates.")
        return bbox_2d


class DetectionResult(BaseModel):
    objects: list[DetectionObject] = Field(default_factory=list)
    raw_response: dict[str, Any] | None = None


class EchoImageResponse(BaseModel):
    success: bool = True
    image_base64: str
    image_width: int
    image_height: int
    mime_type: str


class DetectResponse(BaseModel):
    type: Literal["detected", "no_detection"]
    objects: list[DetectionObject] | None = None
    image_base64: str | None = None
    image_width: int | None = None
    image_height: int | None = None
    mime_type: str | None = None
