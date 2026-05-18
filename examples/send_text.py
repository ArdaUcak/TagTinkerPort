#!/usr/bin/env python3
"""Render text onto a tag.

Usage:
    sudo pigpiod
    python3 send_text.py <17-digit-barcode> "HELLO"
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
from tagtinker.render import text_to_pixels
from tagtinker.sequence import send_full_image


def main() -> int:
    ap = argparse.ArgumentParser(description="Render text onto an ESL tag.")
    ap.add_argument("barcode")
    ap.add_argument("text")
    ap.add_argument("--width", type=int, default=None, help="override width (auto-detected from barcode if known)")
    ap.add_argument("--height", type=int, default=None)
    ap.add_argument("--page", type=int, default=0)
    ap.add_argument("--invert", action="store_true")
    ap.add_argument("--padding-pct", type=int, default=5)
    ap.add_argument("--font", default=None, help="path to a .ttf file")
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
    pixels = text_to_pixels(
        args.text,
        width,
        height,
        invert=args.invert,
        padding_pct=args.padding_pct,
        font_path=args.font,
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
