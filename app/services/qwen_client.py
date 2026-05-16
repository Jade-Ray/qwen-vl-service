import json
import re
from typing import Any

from openai import OpenAI

from app.schemas import DetectionObject, DetectionResult
from app.utils.config import Settings, get_settings


DEFAULT_DETECTION_TASK = "检测图中所有目标"

DETECTION_PROMPT_TEMPLATE = (
    "请检测图中的目标，以JSON格式返回每个目标的边界框2D坐标（bbox_2d）和类别标签（label）。\n"
    "原图宽度为 {image_width} 像素，高度为 {image_height} 像素。\n"
    '只输出 JSON，格式为 {{"objects": [{{"label": "类别名", "bbox_2d": [x1, y1, x2, y2]}}]}}，不要解释或 markdown。\n\n'
    "用户任务：{user_task}"
)


class QwenClientError(Exception):
    pass


class QwenVLClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        if not self.settings.api_key:
            raise RuntimeError("Missing QWEN_API_KEY environment variable.")

        self.client = OpenAI(
            api_key=self.settings.api_key,
            base_url=self.settings.base_url,
        )

    def detect_objects(
        self,
        image_base64: str,
        prompt: str | None,
        image_width: int,
        image_height: int,
        image_mime: str = "image/jpeg",
    ) -> DetectionResult:
        user_task = prompt if prompt else DEFAULT_DETECTION_TASK
        response = self.client.chat.completions.create(
            model=self.settings.model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{image_mime};base64,{image_base64}",
                            },
                        },
                        {
                            "type": "text",
                            "text": DETECTION_PROMPT_TEMPLATE.format(
                                user_task=user_task,
                                image_width=image_width,
                                image_height=image_height,
                            ),
                        },
                    ],
                }
            ],
            max_tokens=self.settings.max_tokens,
            temperature=0,
        )

        content = _coerce_message_content(response.choices[0].message.content)
        payload = _extract_json_object(content)
        objects = _normalize_objects(payload, image_width=image_width, image_height=image_height)
        return DetectionResult(
            objects=[DetectionObject.model_validate(item) for item in objects],
            raw_response=payload,
        )


def _coerce_message_content(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()

    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text = item.get("text")
                if isinstance(text, str):
                    chunks.append(text)
        if chunks:
            return "\n".join(chunks).strip()

    raise QwenClientError("Qwen-VL returned an unsupported response content format.")


def _extract_json_object(content: str) -> dict[str, Any]:
    # strip fenced code blocks (```json ... ``` or ``` ... ```)
    fenced_match = re.search(r"```(?:json)?\s*([\[{].*?)\s*```", content, flags=re.DOTALL)
    candidate = fenced_match.group(1) if fenced_match else content.strip()

    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        # try to extract the outermost JSON value (object or array)
        for start_ch, end_ch in (("{", "}"), ("[", "]")):
            start = candidate.find(start_ch)
            end = candidate.rfind(end_ch)
            if start != -1 and end != -1 and end > start:
                try:
                    parsed = json.loads(candidate[start : end + 1])
                    break
                except json.JSONDecodeError:
                    continue
        else:
            raise QwenClientError(f"Qwen-VL did not return valid JSON: {content}") from None

    # normalise top-level array → {"objects": [...]}
    if isinstance(parsed, list):
        return {"objects": parsed}
    if isinstance(parsed, dict):
        return parsed
    raise QwenClientError("Qwen-VL JSON response must be an object or array.")


def _normalize_objects(payload: dict[str, Any], image_width: int, image_height: int) -> list[dict[str, Any]]:
    raw_objects = payload.get("objects")
    if raw_objects is None:
        raw_objects = payload.get("detections", payload.get("results", []))

    if not isinstance(raw_objects, list):
        raise QwenClientError("Qwen-VL JSON response must contain an objects array.")

    normalized: list[dict[str, Any]] = []
    for item in raw_objects:
        if not isinstance(item, dict):
            continue

        label = _first_string(item, "label", "category", "class", "name")
        if not label:
            continue

        bbox = _extract_bbox(item, image_width=image_width, image_height=image_height)
        score = _extract_score(item)
        normalized.append({"label": label, "bbox_2d": bbox, "score": score})

    return normalized


def _extract_bbox(item: dict[str, Any], image_width: int, image_height: int) -> list[int]:
    # support bbox, bbox_2d, x1/y1/x2/y2, left/top/right/bottom
    for key in ("bbox", "bbox_2d"):
        val = item.get(key)
        if isinstance(val, list) and len(val) == 4:
            coords = val
            break
    else:
        if all(k in item for k in ("x1", "y1", "x2", "y2")):
            coords = [item["x1"], item["y1"], item["x2"], item["y2"]]
        elif all(k in item for k in ("left", "top", "right", "bottom")):
            coords = [item["left"], item["top"], item["right"], item["bottom"]]
        else:
            raise QwenClientError(f"Unsupported bbox format: {item}")

    numeric = [float(value) for value in coords]
    if max(abs(value) for value in numeric) <= 1.5:
        numeric = [
            numeric[0] * image_width,
            numeric[1] * image_height,
            numeric[2] * image_width,
            numeric[3] * image_height,
        ]

    xmin, ymin, xmax, ymax = numeric
    xmin, xmax = sorted((xmin, xmax))
    ymin, ymax = sorted((ymin, ymax))

    clipped = [
        max(0, min(int(round(xmin)), image_width - 1)),
        max(0, min(int(round(ymin)), image_height - 1)),
        max(0, min(int(round(xmax)), image_width - 1)),
        max(0, min(int(round(ymax)), image_height - 1)),
    ]

    if clipped[2] <= clipped[0]:
        clipped[2] = min(image_width - 1, clipped[0] + 1)
    if clipped[3] <= clipped[1]:
        clipped[3] = min(image_height - 1, clipped[1] + 1)
    return clipped


def _extract_score(item: dict[str, Any]) -> float | None:
    for key in ("score", "confidence", "probability"):
        value = item.get(key)
        if value is None:
            continue
        score = float(value)
        return max(0.0, min(score, 1.0))
    return None


def _first_string(item: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None
