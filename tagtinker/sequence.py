"""Build the full IR transmission sequence: wake → params → data → refresh.

Ported from scenes/tagtinker_scene_transmit.c — tx_send_full_payload().
"""
from __future__ import annotations

import time

from . import proto
from .ir import TagTinkerIR


# Repeat counts copied from tagtinker_scene_transmit.c.
PING_REPEATS = 80
PARAM_REPEATS = 15
DATA_REPEATS_DEFAULT = 5
REFRESH_REPEATS = 20

# Inter-frame delays in seconds.
DELAY_AFTER_PING_S = 0.050
DELAY_AFTER_PARAM_S = 0.050
DELAY_AFTER_DATA_S = 0.050
DELAY_PER_32_DATA_FRAMES_S = 0.001


def send_full_image(
    ir: TagTinkerIR,
    plid: bytes,
    payload: proto.ImagePayload,
    page: int,
    width: int,
    height: int,
    pos_x: int = 0,
    pos_y: int = 0,
    data_frame_repeats: int = DATA_REPEATS_DEFAULT,
) -> bool:
    """Wake the tag, push the image payload, and trigger a refresh.

    Returns True if every frame transmitted successfully.
    """
    # 1. Wake ping
    ping = proto.make_ping_frame(plid)
    if not ir.transmit(ping, repeats=PING_REPEATS, gap_units_500us=1):
        return False
    time.sleep(DELAY_AFTER_PING_S)

    # 2. Image parameters
    param = proto.make_image_param_frame(
        plid,
        byte_count=payload.byte_count,
        comp_type=payload.comp_type,
        page=page,
        width=width,
        height=height,
        pos_x=pos_x,
        pos_y=pos_y,
    )
    if not ir.transmit(param, repeats=PARAM_REPEATS, gap_units_500us=1):
        return False
    time.sleep(DELAY_AFTER_PARAM_S)

    # 3. Image data
    chunk = proto.IMAGE_DATA_BYTES_PER_FRAME
    if payload.byte_count % chunk != 0:
        raise ValueError(
            f"payload.byte_count ({payload.byte_count}) is not a multiple of {chunk}"
        )
    frame_count = payload.byte_count // chunk
    for i in range(frame_count):
        slice_ = payload.data[i * chunk : (i + 1) * chunk]
        frame = proto.make_image_data_frame(plid, i, slice_)
        if not ir.transmit(frame, repeats=data_frame_repeats, gap_units_500us=1):
            return False
        if (i + 1) % 32 == 0 and (i + 1) < frame_count:
            time.sleep(DELAY_PER_32_DATA_FRAMES_S)

    time.sleep(DELAY_AFTER_DATA_S)

    # 4. Refresh
    refresh = proto.make_refresh_frame(plid)
    if not ir.transmit(refresh, repeats=REFRESH_REPEATS, gap_units_500us=1):
        return False
    return True
