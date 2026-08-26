#!/usr/bin/env python3
"""Validate the transparent blue macOS icon assets."""

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).parent
ICONSET = ROOT / "icon.iconset"
EXPECTED = {
    "icon_16x16.png": (16, 16),
    "icon_16x16@2x.png": (32, 32),
    "icon_32x32.png": (32, 32),
    "icon_32x32@2x.png": (64, 64),
    "icon_128x128.png": (128, 128),
    "icon_128x128@2x.png": (256, 256),
    "icon_256x256.png": (256, 256),
    "icon_256x256@2x.png": (512, 512),
    "icon_512x512.png": (512, 512),
    "icon_512x512@2x.png": (1024, 1024),
}


def validate(path, expected_size):
    image = Image.open(path).convert("RGBA")
    assert image.size == expected_size, (path, image.size, expected_size)
    width, height = image.size
    probes = [
        (0, 0),
        (width - 1, 0),
        (0, height - 1),
        (width - 1, height - 1),
        (width // 2, 0),
        (width // 2, height - 1),
        (0, height // 2),
        (width - 1, height // 2),
    ]
    for point in probes:
        assert image.getpixel(point) == (0, 0, 0, 0), (path, point, image.getpixel(point))
    center = image.getpixel((width // 2, height // 2))
    assert center[3] == 255, (path, center)
    pixels = list(image.get_flattened_data())
    transparent = sum(pixel[3] == 0 for pixel in pixels)
    opaque = sum(pixel[3] == 255 for pixel in pixels)
    assert transparent > width * height * 0.10, (path, transparent)
    assert opaque > width * height * 0.30, (path, opaque)
    for red, green, blue, alpha in pixels:
        if alpha == 0:
            assert (red, green, blue) == (0, 0, 0), (path, red, green, blue, alpha)
        assert alpha == 0 or alpha >= 32, (path, red, green, blue, alpha)
    for point in ((width // 4, height // 2), (width * 3 // 4, height // 2)):
        red, green, blue, alpha = image.getpixel(point)
        assert alpha >= 250 and blue > red and blue > green, (path, point, image.getpixel(point))


for name, size in EXPECTED.items():
    validate(ICONSET / name, size)
validate(ROOT / "susu_icon_512.png", (512, 512))
print("MACOS_ICON_OK")
