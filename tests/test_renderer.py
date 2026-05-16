from PIL import Image

from app.schemas import DetectionObject
from app.services.renderer import render_detections


def make_blank_image(width: int = 200, height: int = 150) -> Image.Image:
    return Image.new("RGB", (width, height), color=(200, 200, 200))


class TestRenderDetections:
    def test_empty_detections_returns_copy(self) -> None:
        img = make_blank_image()
        result = render_detections(img, [])
        assert result is not img
        assert result.size == img.size

    def test_renders_single_detection(self) -> None:
        img = make_blank_image()
        detections = [DetectionObject(label="cat", bbox_2d=[10, 10, 100, 80])]
        result = render_detections(img, detections)
        assert result.size == img.size
        # The rendered image should differ from the blank original
        assert list(result.getdata()) != list(img.convert("RGB").getdata())

    def test_renders_multiple_detections(self) -> None:
        img = make_blank_image()
        detections = [
            DetectionObject(label="cat", bbox_2d=[10, 10, 80, 60]),
            DetectionObject(label="dog", bbox_2d=[100, 50, 180, 130]),
        ]
        result = render_detections(img, detections)
        assert result.size == img.size

    def test_detection_with_score_label(self) -> None:
        img = make_blank_image()
        detections = [DetectionObject(label="person", bbox_2d=[5, 5, 50, 100], score=0.87)]
        result = render_detections(img, detections)
        assert result.size == img.size

    def test_converts_rgba_to_rgb(self) -> None:
        rgba_img = Image.new("RGBA", (100, 100), color=(255, 0, 0, 200))
        detections = [DetectionObject(label="x", bbox_2d=[0, 0, 50, 50])]
        result = render_detections(rgba_img, detections)
        assert result.mode == "RGB"
