#!/usr/bin/env python3
"""Generate macOS iconset PNGs for iconutil on a Mac runner."""
import glob
import os
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.abspath(__file__))
ICONSET = os.path.join(ROOT, "icon.iconset")
os.makedirs(ICONSET, exist_ok=True)

font_paths = [
    "/System/Library/Fonts/Helvetica.ttc",
    "/System/Library/Fonts/SFNS.ttf",
    "/Library/Fonts/Arial.ttf",
]
font_paths += glob.glob("/System/Library/Fonts/*.ttf")


def find_font(size):
    for path in font_paths:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()

for size in (16, 32, 128, 256, 512):
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    margin = max(1, int(size * 0.05))
    draw.ellipse((margin, margin, size - margin, size - margin), fill=(40, 96, 225, 255))
    font = find_font(max(8, int(size * 0.48)))
    box = draw.textbbox((0, 0), "SS", font=font)
    width = box[2] - box[0]
    height = box[3] - box[1]
    x = (size - width) // 2 - box[0]
    y = int(size * 0.66) - height - box[1]
    draw.text((x, y), "SS", font=font, fill=(255, 255, 255, 255))
    image.save(os.path.join(ICONSET, "icon_%dx%d.png" % (size, size)))
    if size <= 256:
        image.resize((size * 2, size * 2), Image.Resampling.LANCZOS).save(
            os.path.join(ICONSET, "icon_%dx%d@2x.png" % (size, size)))
print(ICONSET)
