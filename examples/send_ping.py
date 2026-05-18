#!/usr/bin/env python3
"""Send a wake-up ping to a tag.

Usage:
    sudo pigpiod
    python3 send_ping.py <17-digit-barcode>
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pigpio

from tagtinker import barcode_to_plid, make_ping_frame
from tagtinker.ir import TagTinkerIR


def main() -> int:
    ap = argparse.ArgumentParser(description="Send one ping frame to an ESL tag.")
    ap.add_argument("barcode", help="17-digit tag barcode (from the NFC scan or label)")
    ap.add_argument("--repeats", type=int, default=80, help="ping repeats (default 80)")
    ap.add_argument("--carrier-gpio", type=int, default=18)
    ap.add_argument("--gate-gpio", type=int, default=17)
    args = ap.parse_args()

    plid = barcode_to_plid(args.barcode)
    frame = make_ping_frame(plid)
    print(f"PLID: {plid.hex()}, frame: {len(frame)} bytes")

    pi = pigpio.pi()
    if not pi.connected:
        print("ERROR: pigpio daemon not running. Start it with: sudo pigpiod", file=sys.stderr)
        return 1

    ir = TagTinkerIR(pi, carrier_gpio=args.carrier_gpio, gate_gpio=args.gate_gpio)
    ir.init()
    try:
        ok = ir.transmit(frame, repeats=args.repeats, gap_units_500us=1)
    finally:
        ir.deinit()
        pi.stop()
    print(f"transmit ok={ok}")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
