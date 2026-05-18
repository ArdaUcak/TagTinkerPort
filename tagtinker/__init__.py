"""TagTinkerPort — Raspberry Pi port of the TagTinker ESL IR toolkit.

Original project: https://github.com/i12bp8/TagTinker (Flipper Zero, GPL-3.0).
This port reuses the wire protocol and timing constants from the C source
and substitutes pigpio for the Flipper's TIM1+DWT hardware path.
"""
from .proto import (
    IMAGE_DATA_BYTES_PER_FRAME,
    MAX_FRAME_SIZE,
    ImagePayload,
    barcode_to_plid,
    barcode_to_profile,
    barcode_to_type,
    crc16,
    encode_image_payload,
    encode_planes_payload,
    is_barcode_valid,
    make_addressed_frame,
    make_broadcast_debug_frame,
    make_broadcast_page_frame,
    make_image_data_frame,
    make_image_param_frame,
    make_ping_frame,
    make_refresh_frame,
)
from .profiles import TagColor, TagKind, TagProfile, all_profiles, lookup_profile

__all__ = [
    "IMAGE_DATA_BYTES_PER_FRAME",
    "MAX_FRAME_SIZE",
    "ImagePayload",
    "TagColor",
    "TagKind",
    "TagProfile",
    "all_profiles",
    "barcode_to_plid",
    "barcode_to_profile",
    "barcode_to_type",
    "crc16",
    "encode_image_payload",
    "encode_planes_payload",
    "is_barcode_valid",
    "lookup_profile",
    "make_addressed_frame",
    "make_broadcast_debug_frame",
    "make_broadcast_page_frame",
    "make_image_data_frame",
    "make_image_param_frame",
    "make_ping_frame",
    "make_refresh_frame",
]


def __getattr__(name: str):
    # Lazy import so that proto/profile tests can run on dev machines
    # without pigpio installed.
    if name in ("TagTinkerIR", "TagTinkerIRError"):
        from .ir import TagTinkerIR, TagTinkerIRError
        return {"TagTinkerIR": TagTinkerIR, "TagTinkerIRError": TagTinkerIRError}[name]
    if name == "send_full_image":
        from .sequence import send_full_image
        return send_full_image
    raise AttributeError(name)
