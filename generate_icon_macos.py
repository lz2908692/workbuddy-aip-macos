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

def render_icon(size):
    scale = 4
    canvas = size * scale
    image = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    margin = max(scale, int(canvas * 0.065))
    draw.ellipse(
        (margin, margin, canvas - margin - 1, canvas - margin - 1),
        fill=(40, 96, 225, 255),
    )
    font = find_font(max(8, int(canvas * 0.43)))
    box = draw.textbbox((0, 0), "SS", font=font)
    width = box[2] - box[0]
    height = box[3] - box[1]
    x = (canvas - width) // 2 - box[0]
    y = (canvas - height) // 2 - box[1] - int(canvas * 0.015)
    draw.text((x, y), "SS", font=font, fill=(255, 255, 255, 255))
    result = image.resize((size, size), Image.Resampling.LANCZOS)
    pixels = result.load()
    for y in range(size):
        for x in range(size):
            red, green, blue, alpha = pixels[x, y]
            if alpha < 32:
                pixels[x, y] = (0, 0, 0, 0)
    return result


for size in (16, 32, 128, 256, 512):
    image = render_icon(size)
    image.save(os.path.join(ICONSET, "icon_%dx%d.png" % (size, size)))
    render_icon(size * 2).save(os.path.join(ICONSET, "icon_%dx%d@2x.png" % (size, size)))
render_icon(512).save(os.path.join(ROOT, "susu_icon_512.png"))
print(ICONSET)
