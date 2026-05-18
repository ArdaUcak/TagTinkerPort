"""Image and text rendering helpers — replaces the Flipper's render_text_ex.

Uses Pillow to do the heavy lifting (any image format, resampling, fonts).
Output is the flat 0/1 byte array that proto.encode_planes_payload expects.
"""
from __future__ import annotations

from typing import Optional

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError as exc:
    raise ImportError(
        "Pillow is required for image/text rendering. Install with: pip install Pillow"
    ) from exc


def image_to_pixels(
    path: str,
    width: int,
    height: int,
    threshold: int = 128,
    dither: bool = True,
) -> bytes:
    """Load an image file, resize to (width, height), return flat 0/1 bytes.

    1 = ink (dark), 0 = paper (light). One byte per pixel.
    """
    img = Image.open(path).convert("L").resize((width, height), Image.Resampling.LANCZOS)
    if dither:
        bw = img.convert("1", dither=Image.Dither.FLOYDSTEINBERG)
        data = bw.tobytes()
        out = bytearray(width * height)
        # PIL "1" mode packs 8 pixels per byte, MSB first.
        for y in range(height):
            row_off = y * ((width + 7) // 8)
            for x in range(width):
                bit = (data[row_off + (x >> 3)] >> (7 - (x & 7))) & 1
                out[y * width + x] = 0 if bit else 1
        return bytes(out)
    raw = img.tobytes()
    out = bytearray(width * height)
    for i, v in enumerate(raw):
        out[i] = 1 if v < threshold else 0
    return bytes(out)


def _load_font(size: int, font_path: Optional[str]) -> ImageFont.ImageFont:
    if font_path:
        return ImageFont.truetype(font_path, size)
    for candidate in (
        "DejaVuSans-Bold.ttf",
        "DejaVuSans.ttf",
        "LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ):
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def text_to_pixels(
    text: str,
    width: int,
    height: int,
    invert: bool = False,
    padding_pct: int = 5,
    font_path: Optional[str] = None,
) -> bytes:
    """Render `text` centered onto a (width, height) bitmap of 0/1 bytes."""
    img = Image.new("L", (width, height), 255)
    draw = ImageDraw.Draw(img)

    pad_x = max(1, (width * padding_pct) // 100)
    pad_y = max(1, (height * padding_pct) // 100)
    box_w = max(1, width - 2 * pad_x)
    box_h = max(1, height - 2 * pad_y)

    # Binary search for the largest font size that fits the box.
    lo, hi = 6, max(8, height)
    best = None
    while lo <= hi:
        mid = (lo + hi) // 2
        font = _load_font(mid, font_path)
        bbox = draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        if tw <= box_w and th <= box_h:
            best = (mid, tw, th, bbox)
            lo = mid + 1
        else:
            hi = mid - 1
    if best is None:
        font = _load_font(8, font_path)
        bbox = draw.textbbox((0, 0), text, font=font)
        best = (8, bbox[2] - bbox[0], bbox[3] - bbox[1], bbox)

    size, tw, th, bbox = best
    font = _load_font(size, font_path)
    x = (width - tw) // 2 - bbox[0]
    y = (height - th) // 2 - bbox[1]
    draw.text((x, y), text, fill=0, font=font)

    raw = img.tobytes()
    out = bytearray(width * height)
    for i, v in enumerate(raw):
        ink = v < 128
        if invert:
            ink = not ink
        out[i] = 1 if ink else 0
    return bytes(out)
