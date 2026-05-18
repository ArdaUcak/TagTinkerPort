#!/usr/bin/env python3
"""Send any image file to a tag (PNG, JPG, BMP, GIF, ...).

Usage:
    sudo pigpiod
    python3 send_image.py <17-digit-barcode> path/to/image.png
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pigpio

from tagtinker import (
    barcode_to_plid,
    barcode_to_profile,
    encode_planes_payload,
)
from tagtinker.ir import TagTinkerIR
from tagtinker.render import image_to_pixels
from tagtinker.sequence import send_full_image


def main() -> int:
    ap = argparse.ArgumentParser(description="Send an image to an ESL tag.")
    ap.add_argument("barcode")
    ap.add_argument("image_path")
    ap.add_argument("--width", type=int, default=None)
    ap.add_argument("--height", type=int, default=None)
    ap.add_argument("--page", type=int, default=0)
    ap.add_argument("--threshold", type=int, default=128, help="threshold for non-dither mode")
    ap.add_argument("--no-dither", action="store_true", help="disable Floyd-Steinberg dithering")
    ap.add_argument("--data-repeats", type=int, default=5)
    ap.add_argument("--carrier-gpio", type=int, default=18)
    ap.add_argument("--gate-gpio", type=int, default=17)
    args = ap.parse_args()

    profile = barcode_to_profile(args.barcode)
    width = args.width or (profile.width if profile else 0)
    height = args.height or (profile.height if profile else 0)
    if width == 0 or height == 0:
        print(
            f"unknown tag type {args.barcode[12:16]} — pass --width and --height",
            file=sys.stderr,
        )
        return 1

    plid = barcode_to_plid(args.barcode)
    pixels = image_to_pixels(
        args.image_path, width, height,
        threshold=args.threshold,
        dither=not args.no_dither,
    )
    payload = encode_planes_payload(pixels, None, mode="auto")
    print(
        f"PLID: {plid.hex()}  size: {width}x{height}  "
        f"payload: {payload.byte_count} bytes  "
        f"comp: {'rle' if payload.comp_type == 2 else 'raw'}"
    )

    pi = pigpio.pi()
    if not pi.connected:
        print("ERROR: pigpio daemon not running. Start it with: sudo pigpiod", file=sys.stderr)
        return 1

    ir = TagTinkerIR(pi, carrier_gpio=args.carrier_gpio, gate_gpio=args.gate_gpio)
    ir.init()
    try:
        ok = send_full_image(
            ir, plid, payload,
            page=args.page, width=width, height=height,
            data_frame_repeats=args.data_repeats,
        )
    finally:
        ir.deinit()
        pi.stop()
    print(f"transmit ok={ok}")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
