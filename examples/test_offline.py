#!/usr/bin/env python3
"""Offline self-test — runs on any machine (no Pi, no pigpio needed).

Verifies the protocol port against a few known values and prints the
hex bytes of a ping/refresh/param frame so you can compare with the
Flipper if you have a way to capture frames there.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tagtinker import (
    barcode_to_plid,
    barcode_to_profile,
    barcode_to_type,
    crc16,
    encode_planes_payload,
    make_image_data_frame,
    make_image_param_frame,
    make_ping_frame,
    make_refresh_frame,
)


def main() -> int:
    barcode = "21099601234567890"  # 17 digits, type code = 6789
    assert len(barcode) == 17

    plid = barcode_to_plid(barcode)
    type_code = barcode_to_type(barcode)
    profile = barcode_to_profile(barcode)

    print(f"barcode  : {barcode}")
    print(f"plid     : {plid.hex()}  ({[hex(b) for b in plid]})")
    print(f"type     : {type_code}  profile={profile}")
    print()

    ping = make_ping_frame(plid)
    refresh = make_refresh_frame(plid)
    print(f"ping  ({len(ping):3d} bytes): {ping.hex()}")
    print(f"refr  ({len(refresh):3d} bytes): {refresh.hex()}")

    # 8x4 checkerboard image
    pixels = bytes([(((x + y) & 1)) for y in range(4) for x in range(8)])
    payload = encode_planes_payload(pixels, None, mode="auto")
    print(
        f"\npayload: {payload.byte_count} bytes, "
        f"comp_type={payload.comp_type} ({'rle' if payload.comp_type == 2 else 'raw'})"
    )
    print(f"payload hex: {payload.data.hex()}")

    param = make_image_param_frame(
        plid,
        byte_count=payload.byte_count,
        comp_type=payload.comp_type,
        page=0,
        width=8,
        height=4,
    )
    print(f"\nparam ({len(param):3d} bytes): {param.hex()}")

    chunk = payload.data[:20]
    data = make_image_data_frame(plid, 0, chunk)
    print(f"data0 ({len(data):3d} bytes): {data.hex()}")

    # Sanity: CRC of (frame minus last 2 bytes) should equal last 2 bytes LE.
    body = ping[:-2]
    crc = crc16(body)
    expected = ping[-2] | (ping[-1] << 8)
    assert crc == expected, f"CRC mismatch: {crc:04x} vs {expected:04x}"
    print("\nCRC self-check: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
