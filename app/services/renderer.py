from itertools import cycle

from PIL import Image, ImageDraw, ImageFont

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
    font = ImageFont.load_default()
    line_width = max(2, round(min(canvas.size) / 200))
    palette = cycle(PALETTE)

    for detection in detections:
        color = next(palette)
        xmin, ymin, xmax, ymax = detection.bbox_2d
        draw.rectangle((xmin, ymin, xmax, ymax), outline=color, width=line_width)

        label = detection.label
        if detection.score is not None:
            label = f"{label} {detection.score:.2f}"

        text_bbox = draw.textbbox((xmin, ymin), label, font=font)
        text_width = text_bbox[2] - text_bbox[0]
        text_height = text_bbox[3] - text_bbox[1]

        text_x = xmin
        text_y = max(0, ymin - text_height - 6)
        background = (text_x, text_y, text_x + text_width + 6, text_y + text_height + 4)
        draw.rectangle(background, fill=color)
        draw.text((text_x + 3, text_y + 2), label, fill="white", font=font)

    return canvas
