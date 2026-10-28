"""Draw the app icons (a jar on green) as PNGs, with no image library.

Usage:
    python scripts/make_icons.py

Shapes are signed-distance rounded rectangles, anti-aliased by pixel coverage.
Writes into app/web/static/icons/.
"""

import math
import struct
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "app" / "web" / "static" / "icons"

GREEN = (0x2F, 0x6F, 0x4E)
CREAM = (0xF6, 0xF5, 0xF1)
AMBER = (0xF0, 0xB3, 0x5A)

# Jar parts in unit coordinates (0..1), as (center_x, center_y, half_w, half_h, radius, color).
JAR = [
    (0.50, 0.255, 0.20, 0.050, 0.030, CREAM),  # lid
    (0.50, 0.565, 0.26, 0.245, 0.100, CREAM),  # body
    (0.50, 0.575, 0.26, 0.075, 0.000, AMBER),  # label
]


def rounded_box_sdf(px: float, py: float, cx: float, cy: float, hw: float, hh: float, r: float) -> float:
    qx = abs(px - cx) - (hw - r)
    qy = abs(py - cy) - (hh - r)
    outside = math.hypot(max(qx, 0.0), max(qy, 0.0))
    inside = min(max(qx, qy), 0.0)
    return outside + inside - r


def coverage(distance: float, size: int) -> float:
    """Share of a pixel inside a shape, from its signed distance in unit coordinates."""
    return min(1.0, max(0.0, 0.5 - distance * size))


def render(size: int, *, full_bleed: bool, glyph_scale: float) -> bytes:
    rows = []
    for y in range(size):
        row = bytearray([0])  # PNG filter type 0
        py = (y + 0.5) / size
        for x in range(size):
            px = (x + 0.5) / size
            if full_bleed:
                alpha = 1.0
            else:
                alpha = coverage(rounded_box_sdf(px, py, 0.5, 0.5, 0.5, 0.5, 0.22), size)
            color = list(GREEN)
            # Scale the glyph about the center: sample the unscaled shape at the mapped point.
            gx = 0.5 + (px - 0.5) / glyph_scale
            gy = 0.5 + (py - 0.5) / glyph_scale
            for cx, cy, hw, hh, r, part_color in JAR:
                cov = coverage(rounded_box_sdf(gx, gy, cx, cy, hw, hh, r) * glyph_scale, size)
                if cov > 0:
                    color = [round(c + (p - c) * cov) for c, p in zip(color, part_color)]
            row += bytes(color) + bytes([round(alpha * 255)])
        rows.append(bytes(row))
    return _png(size, size, b"".join(rows))


def _png(width: int, height: int, raw_rgba: bytes) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)  # 8-bit RGBA
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw_rgba, 9))
        + chunk(b"IEND", b"")
    )


ICONS = {
    # name: (size, full_bleed, glyph_scale)
    "icon-192.png": (192, False, 1.0),
    "icon-512.png": (512, False, 1.0),
    # Maskable: platforms crop to a shape; keep the glyph inside the central safe circle.
    "icon-maskable-512.png": (512, True, 0.78),
    # iOS rounds the corners itself and shows transparency as black, so fill the square.
    "apple-touch-icon.png": (180, True, 0.9),
    "favicon-32.png": (32, False, 1.0),
}


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, (size, full_bleed, scale) in ICONS.items():
        (OUT_DIR / name).write_bytes(render(size, full_bleed=full_bleed, glyph_scale=scale))
        print(f"wrote {name} ({size}x{size})", file=sys.stderr)


if __name__ == "__main__":
    main()
