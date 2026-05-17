from itertools import cycle

from PIL import Image, ImageDraw

from app.schemas import DetectionObject


PALETTE = [
    "#ef4444",
    "#f97316",
    "#eab308",
    "#22c55e",
    "#06b6d4",
    "#3b82f6",
    "#a855f7",
    "#ec4899",
]


def render_detections(image: Image.Image, detections: list[DetectionObject]) -> Image.Image:
    canvas = image.convert("RGB").copy()
    if not detections:
        return canvas

    draw = ImageDraw.Draw(canvas)
    line_width = max(2, round(min(canvas.size) / 200))
    palette = cycle(PALETTE)

    for detection in detections:
        color = next(palette)
        xmin, ymin, xmax, ymax = detection.bbox_2d
        draw.rectangle((xmin, ymin, xmax, ymax), outline=color, width=line_width)

    return canvas
