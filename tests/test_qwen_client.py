"""Unit tests for qwen_client JSON parsing and normalisation helpers."""
import pytest

from app.services.qwen_client import (
    QwenClientError,
    _coerce_message_content,
    _extract_json_object,
    _normalize_objects,
)


class TestCoerceMessageContent:
    def test_string_content(self) -> None:
        assert _coerce_message_content("  hello  ") == "hello"

    def test_list_content_single_text(self) -> None:
        content = [{"type": "text", "text": "hello"}]
        assert _coerce_message_content(content) == "hello"

    def test_list_content_multiple_text_joined(self) -> None:
        content = [
            {"type": "text", "text": "line1"},
            {"type": "image_url", "url": "..."},   # ignored
            {"type": "text", "text": "line2"},
        ]
        assert _coerce_message_content(content) == "line1\nline2"

    def test_list_with_no_text_raises(self) -> None:
        with pytest.raises(QwenClientError, match="unsupported"):
            _coerce_message_content([{"type": "image_url"}])

    def test_unsupported_type_raises(self) -> None:
        with pytest.raises(QwenClientError, match="unsupported"):
            _coerce_message_content(12345)  # type: ignore[arg-type]


class TestExtractJsonObject:
    def test_plain_json_object(self) -> None:
        result = _extract_json_object('{"objects": []}')
        assert result == {"objects": []}

    def test_plain_json_array_wrapped(self) -> None:
        result = _extract_json_object('[{"label": "cat", "bbox_2d": [0,0,1,1]}]')
        assert "objects" in result
        assert len(result["objects"]) == 1

    def test_fenced_json_block(self) -> None:
        result = _extract_json_object('```json\n{"objects": []}\n```')
        assert result == {"objects": []}

    def test_fenced_block_no_language_tag(self) -> None:
        result = _extract_json_object('```\n{"objects": []}\n```')
        assert result == {"objects": []}

    def test_json_embedded_in_text(self) -> None:
        result = _extract_json_object('Here you go: {"objects": []} Done.')
        assert result == {"objects": []}

    def test_invalid_json_raises(self) -> None:
        with pytest.raises(QwenClientError, match="valid JSON"):
            _extract_json_object("no json here at all")

    def test_scalar_json_raises(self) -> None:
        with pytest.raises(QwenClientError):
            _extract_json_object("42")


class TestNormalizeObjects:
    def test_empty_objects(self) -> None:
        assert _normalize_objects({"objects": []}, 640, 480) == []

    def test_bbox_2d_qwen_normalized_1000_space(self) -> None:
        """0-1000 coords on a 1920×1080 image should be scaled to pixels."""
        payload = {"objects": [{"label": "car", "bbox_2d": [100, 500, 400, 900]}]}
        result = _normalize_objects(payload, 1920, 1080)
        assert result[0]["label"] == "car"
        # 100/1000*1920=192, 500/1000*1080=540, 400/1000*1920=768, 900/1000*1080=972
        assert result[0]["bbox_2d"] == [192, 540, 768, 972]

    def test_bbox_field_alias_qwen_normalized(self) -> None:
        """bbox alias field also supports 0-1000 coords."""
        payload = {"objects": [{"label": "dog", "bbox": [0, 0, 500, 500]}]}
        result = _normalize_objects(payload, 1000, 1000)
        assert result[0]["bbox_2d"] == [0, 0, 500, 500]

    def test_x1y1x2y2_format(self) -> None:
        """x1/y1/x2/y2 fields with 0-1000 coords on square image."""
        payload = {"objects": [{"label": "car", "x1": 100, "y1": 200, "x2": 400, "y2": 800}]}
        result = _normalize_objects(payload, 1000, 1000)
        assert result[0]["bbox_2d"] == [100, 200, 400, 800]

    def test_pixel_coords_above_1000_unchanged(self) -> None:
        """Pixel coordinates > 1000 must not be rescaled."""
        payload = {"objects": [{"label": "car", "bbox_2d": [1100, 200, 1500, 600]}]}
        result = _normalize_objects(payload, 1920, 1080)
        assert result[0]["bbox_2d"] == [1100, 200, 1500, 600]

    def test_zero_to_one_normalized_coordinates_scaled(self) -> None:
        """Legacy 0-1 normalised floats should scale by image dimensions."""
        payload = {"objects": [{"label": "cat", "bbox_2d": [0.1, 0.2, 0.5, 0.8]}]}
        result = _normalize_objects(payload, 100, 100)
        assert result[0]["bbox_2d"] == [10, 20, 50, 80]

    def test_skips_items_without_label(self) -> None:
        payload = {
            "objects": [
                {"bbox_2d": [0, 0, 10, 10]},                     # no label → skip
                {"label": "dog", "bbox_2d": [0, 0, 10, 10]},
            ]
        }
        result = _normalize_objects(payload, 640, 480)
        assert len(result) == 1
        assert result[0]["label"] == "dog"

    def test_score_extracted(self) -> None:
        payload = {"objects": [{"label": "cat", "bbox_2d": [0, 0, 10, 10], "score": 0.92}]}
        result = _normalize_objects(payload, 640, 480)
        assert result[0]["score"] == pytest.approx(0.92)

    def test_no_score_returns_none(self) -> None:
        payload = {"objects": [{"label": "cat", "bbox_2d": [0, 0, 10, 10]}]}
        result = _normalize_objects(payload, 640, 480)
        assert result[0]["score"] is None

    def test_detections_fallback_key(self) -> None:
        payload = {"detections": [{"label": "dog", "bbox_2d": [0, 0, 10, 10]}]}
        result = _normalize_objects(payload, 640, 480)
        assert len(result) == 1

    def test_unsupported_bbox_raises(self) -> None:
        payload = {"objects": [{"label": "cat", "no_bbox_key": True}]}
        with pytest.raises(QwenClientError):
            _normalize_objects(payload, 640, 480)

    def test_non_list_objects_raises(self) -> None:
        with pytest.raises(QwenClientError):
            _normalize_objects({"objects": "not a list"}, 640, 480)
