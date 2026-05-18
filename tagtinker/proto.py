"""ESL protocol helpers — pure-Python port of protocol/tagtinker_proto.c.

Builds the byte-level frames the tag expects: ping, image params, image
data chunks, refresh, and broadcast variants. No hardware dependency
here — this module is unit-testable on any platform.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .profiles import TagProfile, lookup_profile

PROTO_DM = 0x85
PROTO_SEG = 0x84
MAX_FRAME_SIZE = 96
IMAGE_DATA_BYTES_PER_FRAME = 20

CRC16_POLY = 0x8408
CRC16_INIT = 0x8408


def crc16(data: bytes) -> int:
    """CRC-16 used by the ESL wire format (poly 0x8408, init 0x8408)."""
    crc = CRC16_INIT
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ CRC16_POLY
            else:
                crc >>= 1
    return crc & 0xFFFF


def _terminate(buf: bytearray) -> bytes:
    crc = crc16(bytes(buf))
    buf.append(crc & 0xFF)
    buf.append((crc >> 8) & 0xFF)
    return bytes(buf)


def _raw_frame(proto: int, plid: bytes, cmd: int) -> bytearray:
    if len(plid) != 4:
        raise ValueError("plid must be 4 bytes")
    return bytearray([proto, plid[0], plid[1], plid[2], plid[3], cmd])


def _mcu_frame(plid: bytes, cmd: int) -> bytearray:
    buf = _raw_frame(PROTO_DM, plid, 0x34)
    buf += bytes([0x00, 0x00, 0x00, cmd])
    return buf


def _append_word(buf: bytearray, value: int) -> None:
    buf.append((value >> 8) & 0xFF)
    buf.append(value & 0xFF)


# ----- barcode helpers -----

def is_barcode_valid(barcode: str) -> bool:
    return isinstance(barcode, str) and len(barcode) == 17 and barcode.isdigit()


def barcode_to_plid(barcode: str) -> bytes:
    """Decode a 17-character barcode into the 4-byte PLID (LSB first).

    Mirrors tagtinker_barcode_to_plid: bytes[2..7) + bytes[7..12) form a
    pair of 5-digit groups, packed as (a << 16) | b and stored little-endian.
    """
    if not is_barcode_valid(barcode):
        raise ValueError("barcode must be 17 numeric characters")
    a = int(barcode[2:7])
    b = int(barcode[7:12])
    id_val = (a << 16) | b
    return bytes([
        id_val & 0xFF,
        (id_val >> 8) & 0xFF,
        (id_val >> 16) & 0xFF,
        (id_val >> 24) & 0xFF,
    ])


def barcode_to_type(barcode: str) -> int:
    if not is_barcode_valid(barcode):
        raise ValueError("barcode must be 17 numeric characters")
    return int(barcode[12:16])


def barcode_to_profile(barcode: str) -> Optional[TagProfile]:
    return lookup_profile(barcode_to_type(barcode))


# ----- frame builders -----

def make_ping_frame(plid: bytes) -> bytes:
    """Wake-up ping. Send before any addressed command."""
    buf = _raw_frame(PROTO_DM, plid, 0x97)
    buf += bytes([0x01, 0x00, 0x00, 0x00])
    buf += bytes([0x01] * 20)
    return _terminate(buf)


def make_refresh_frame(plid: bytes) -> bytes:
    """Commit pending image data and update the display."""
    buf = _mcu_frame(plid, 0x01)
    buf += bytes([0x00] * 18)
    return _terminate(buf)


def make_image_param_frame(
    plid: bytes,
    byte_count: int,
    comp_type: int,
    page: int,
    width: int,
    height: int,
    pos_x: int = 0,
    pos_y: int = 0,
) -> bytes:
    """Tell the tag how much image data to expect and where to draw it."""
    buf = _mcu_frame(plid, 0x05)
    _append_word(buf, byte_count)
    buf.append(0x00)
    buf.append(comp_type)
    buf.append(page)
    _append_word(buf, width)
    _append_word(buf, height)
    _append_word(buf, pos_x)
    _append_word(buf, pos_y)
    _append_word(buf, 0x0000)
    buf.append(0x88)
    _append_word(buf, 0x0000)
    buf += bytes([0x00] * 4)
    return _terminate(buf)


def make_image_data_frame(plid: bytes, frame_index: int, data: bytes) -> bytes:
    """Carry IMAGE_DATA_BYTES_PER_FRAME (20) bytes of image payload."""
    if len(data) != IMAGE_DATA_BYTES_PER_FRAME:
        raise ValueError(f"data must be exactly {IMAGE_DATA_BYTES_PER_FRAME} bytes")
    buf = _mcu_frame(plid, 0x20)
    _append_word(buf, frame_index)
    buf += data
    return _terminate(buf)


def make_broadcast_page_frame(page: int, forever: bool, duration: int) -> bytes:
    """Page-select for all listening tags (PLID = 00 00 00 00)."""
    buf = _raw_frame(PROTO_DM, bytes(4), 0x06)
    buf.append(((page & 7) << 3) | 0x01 | (0x80 if forever else 0x00))
    buf.append(0x00)
    buf.append(0x00)
    buf.append((duration >> 8) & 0xFF)
    buf.append(duration & 0xFF)
    return _terminate(buf)


def make_broadcast_debug_frame() -> bytes:
    buf = _raw_frame(PROTO_DM, bytes(4), 0x06)
    buf += bytes([0xF1, 0x00, 0x00, 0x00, 0x0A])
    return _terminate(buf)


def make_addressed_frame(plid: bytes, payload: bytes) -> bytes:
    if len(payload) < 1:
        raise ValueError("payload must contain at least the command byte")
    buf = _raw_frame(PROTO_DM, plid, payload[0])
    buf += payload[1:]
    return _terminate(buf)


# ----- bit writer + RLE (Elias-gamma-like) -----

class _BitWriter:
    """Append bits efficiently into a growing bytearray."""

    __slots__ = ("buf", "bit_pos")

    def __init__(self) -> None:
        self.buf = bytearray(64)
        self.bit_pos = 0

    def _ensure(self, additional_bits: int) -> None:
        needed = (self.bit_pos + additional_bits + 7) // 8
        if needed > len(self.buf):
            new_size = max(needed, len(self.buf) * 2)
            self.buf.extend(bytes(new_size - len(self.buf)))

    def append(self, bit: int) -> None:
        self._ensure(1)
        if bit & 1:
            self.buf[self.bit_pos >> 3] |= 1 << (7 - (self.bit_pos & 7))
        self.bit_pos += 1

    def append_run(self, count: int) -> None:
        """Elias-gamma-like run encoding: (n-1) zero prefix + n MSB-first bits."""
        n = count.bit_length()
        if n == 0:
            return
        self._ensure(2 * n - 1)
        self.bit_pos += (n - 1)  # leading zeros
        for i in range(n - 1, -1, -1):
            if (count >> i) & 1:
                self.buf[self.bit_pos >> 3] |= 1 << (7 - (self.bit_pos & 7))
            self.bit_pos += 1

    def to_bytes(self, pad_to_bits: int = 0) -> bytes:
        total = self.bit_pos
        if pad_to_bits:
            extra = (-total) % pad_to_bits
            self._ensure(extra)
            total += extra
        return bytes(self.buf[: (total + 7) // 8])


def _rle_run_bit_length(count: int) -> int:
    return 2 * count.bit_length() - 1


def _iter_pixels(p1: bytes, p2: Optional[bytes]):
    yield from p1
    if p2 is not None:
        yield from p2


def _rle_bit_length(p1: bytes, p2: Optional[bytes]) -> int:
    total = len(p1) + (len(p2) if p2 is not None else 0)
    if total == 0:
        return 0
    bit_len = 1
    it = _iter_pixels(p1, p2)
    run_pixel = next(it)
    run_count = 1
    for pix in it:
        if pix == run_pixel:
            run_count += 1
        else:
            bit_len += _rle_run_bit_length(run_count)
            run_pixel = pix
            run_count = 1
    if run_count > 0:
        bit_len += _rle_run_bit_length(run_count)
    return bit_len


def _pack_raw(p1: bytes, p2: Optional[bytes]) -> _BitWriter:
    w = _BitWriter()
    for pix in _iter_pixels(p1, p2):
        w.append(pix)
    return w


def _pack_rle(p1: bytes, p2: Optional[bytes]) -> _BitWriter:
    w = _BitWriter()
    it = _iter_pixels(p1, p2)
    try:
        run_pixel = next(it)
    except StopIteration:
        return w
    run_count = 1
    w.append(run_pixel)
    for pix in it:
        if pix == run_pixel:
            run_count += 1
        else:
            w.append_run(run_count)
            run_pixel = pix
            run_count = 1
    if run_count > 0:
        w.append_run(run_count)
    return w


@dataclass
class ImagePayload:
    """Encoded image data ready to be split into image_data frames.

    `comp_type`: 0 = raw, 2 = RLE.
    `byte_count` is always a multiple of IMAGE_DATA_BYTES_PER_FRAME.
    """

    data: bytes
    byte_count: int
    comp_type: int


def encode_planes_payload(
    primary: bytes,
    secondary: Optional[bytes] = None,
    mode: str = "auto",
) -> ImagePayload:
    """Encode one or two pixel planes into a tag wire payload.

    `primary` and `secondary` are flat byte arrays where each byte is 0
    or 1 (one byte per pixel). Length must equal width*height.

    `mode`:
      - 'auto': use RLE if it is strictly smaller than raw, else raw.
      - 'raw': always raw (1 bit per pixel).
      - 'rle': always RLE.
    """
    if mode not in ("auto", "raw", "rle"):
        raise ValueError("mode must be 'auto', 'raw', or 'rle'")

    total_pixels = len(primary) + (len(secondary) if secondary is not None else 0)
    rle_bits = _rle_bit_length(primary, secondary)
    use_compressed = (
        mode == "rle"
        or (mode == "auto" and rle_bits > 0 and rle_bits < total_pixels)
    )

    writer = _pack_rle(primary, secondary) if use_compressed else _pack_raw(primary, secondary)
    chunk_bits = IMAGE_DATA_BYTES_PER_FRAME * 8
    packed = writer.to_bytes(pad_to_bits=chunk_bits)
    return ImagePayload(
        data=packed,
        byte_count=len(packed),
        comp_type=2 if use_compressed else 0,
    )


def encode_image_payload(
    pixels: bytes,
    width: int,
    height: int,
    color_clear: bool = False,
    mode: str = "auto",
) -> ImagePayload:
    """Convenience wrapper. If `color_clear` is True, a second plane of all-1s
    is appended (matches tagtinker_encode_image_payload in the C source).
    """
    expected = width * height
    if len(pixels) != expected:
        raise ValueError(f"pixels length {len(pixels)} != width*height ({expected})")
    secondary: Optional[bytes] = bytes([1]) * expected if color_clear else None
    return encode_planes_payload(pixels, secondary, mode=mode)
