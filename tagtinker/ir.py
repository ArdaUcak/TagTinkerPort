"""IR transmitter for TagTinker — pigpio port of ir/tagtinker_ir.c.

The Flipper drives a 1.255 MHz carrier on TIM1 CH3N and uses PP4 (Pulse
Position 4) symbol timing: a ~40 µs burst followed by a gap whose length
selects one of four 2-bit symbol values.

On the Pi we split the same job across two GPIO pins:

  - `carrier_gpio` (default GPIO 18 = PWM0): pigpio hardware PWM at
    1.255 MHz, ~50% duty, runs continuously during a transmit() call.
  - `gate_gpio` (default GPIO 17): pigpio DMA-clocked waveform. HIGH
    for each 40 µs burst, LOW for the symbol gap.

An external transistor ANDs the two together so the IR LED only emits
when both are HIGH. See wiring.md.

Runtime requirements on the Pi:

  - **pigpiod must run with `-s 1`** (1 µs sample rate). The default 5 µs
    sample rate rounds the 121/181/242 µs symbol gaps down to 120/180/240,
    introducing 0.4–0.8 % timing error that some tags decode unreliably.
    `setup_hotspot.sh` installs a systemd drop-in that sets this; if you
    run pigpiod manually use: `sudo pigpiod -s 1`.
  - **The PWM0 peripheral conflicts with the on-board audio driver.**
    Raspberry Pi OS ships with `dtparam=audio=on`, which binds PWM0/PWM1
    to bcm2835-audio. Disable it in /boot/firmware/config.txt before
    transmitting, or move the carrier to GPIO 13/19 (PWM1) which is also
    affected but at least lets you pick a free channel.
"""
from __future__ import annotations

import time
from typing import List

import pigpio


# PP4 symbol timing in microseconds (cycles in the C source / 64 MHz).
#   Burst:      2581 cycles  ≈  40 µs
#   Gap sym 0:  3871 cycles  ≈  60 µs
#   Gap sym 1: 15483 cycles  ≈ 242 µs
#   Gap sym 2:  7741 cycles  ≈ 121 µs
#   Gap sym 3: 11612 cycles  ≈ 181 µs
BURST_US = 40
GAP_US_BY_SYMBOL = (60, 242, 121, 181)

DEFAULT_CARRIER_FREQ_HZ = 1_255_000
DEFAULT_CARRIER_GPIO = 18   # PWM0 (BCM). Other PWM-capable pins: 12, 13, 19.
DEFAULT_GATE_GPIO = 17      # any free GPIO

# A pigpio wave can hold ~12000 pulses. Each frame byte produces 8 pulses
# (4 symbols × {burst, gap}), plus the closing burst and tail. The Flipper
# caps frame length at 255 bytes — well within the wave buffer.
_HARDWARE_PWM_DUTY_50 = 500_000  # pigpio dutycycle scale is 0..1_000_000


class TagTinkerIRError(RuntimeError):
    pass


class TagTinkerIR:
    """pigpio-driven IR transmitter for TagTinker ESL frames.

    Example:
        import pigpio
        from tagtinker import TagTinkerIR

        pi = pigpio.pi()
        ir = TagTinkerIR(pi)
        ir.init()
        try:
            ir.transmit(frame_bytes, repeats=80)
        finally:
            ir.deinit()
            pi.stop()
    """

    def __init__(
        self,
        pi: pigpio.pi,
        carrier_gpio: int = DEFAULT_CARRIER_GPIO,
        gate_gpio: int = DEFAULT_GATE_GPIO,
        carrier_freq_hz: int = DEFAULT_CARRIER_FREQ_HZ,
    ) -> None:
        if not pi.connected:
            raise TagTinkerIRError(
                "pigpio daemon is not running. Start it with: sudo pigpiod -s 1"
            )
        if carrier_gpio == gate_gpio:
            raise ValueError("carrier_gpio and gate_gpio must differ")
        self.pi = pi
        self.carrier_gpio = carrier_gpio
        self.gate_gpio = gate_gpio
        self.carrier_freq_hz = carrier_freq_hz
        self._initialized = False
        self._stop_requested = False

    # ---------- lifecycle ----------

    def init(self) -> None:
        if self._initialized:
            return
        self.pi.set_mode(self.gate_gpio, pigpio.OUTPUT)
        self.pi.write(self.gate_gpio, 0)
        self.pi.set_mode(self.carrier_gpio, pigpio.OUTPUT)
        self.pi.write(self.carrier_gpio, 0)
        self.pi.wave_clear()
        self._initialized = True

    def deinit(self) -> None:
        if not self._initialized:
            return
        self.stop()
        self._carrier_off()
        self.pi.write(self.gate_gpio, 0)
        self.pi.wave_clear()
        self._initialized = False

    # ---------- public API ----------

    def transmit(
        self,
        data: bytes,
        repeats: int = 0,
        gap_units_500us: int = 0,
    ) -> bool:
        """Transmit one PP4-encoded frame, repeating `repeats` extra times.

        `gap_units_500us` mirrors the Flipper's `delay` parameter — each
        unit is 500 µs of additional silence between consecutive repeats.

        Returns False if stop() was called mid-burst.
        """
        if not self._initialized:
            raise TagTinkerIRError("call init() before transmit()")
        if not data or len(data) > 255:
            raise ValueError("frame length must be 1..255 bytes")

        self._stop_requested = False
        repeats = max(0, int(repeats) & 0x7FFF)

        wave_id = self._build_frame_wave(data)
        try:
            self._carrier_on()
            try:
                for rep in range(repeats + 1):
                    if self._stop_requested:
                        return False
                    self.pi.wave_send_once(wave_id)
                    while self.pi.wave_tx_busy():
                        if self._stop_requested:
                            self.pi.wave_tx_stop()
                            return False
                        time.sleep(0.0005)
                    if rep < repeats and gap_units_500us > 0:
                        time.sleep(gap_units_500us * 0.0005)
            finally:
                self._carrier_off()
        finally:
            self.pi.wave_delete(wave_id)
        return True

    def stop(self) -> None:
        """Abort an in-flight transmission and silence the LED."""
        self._stop_requested = True
        try:
            self.pi.wave_tx_stop()
        except Exception:
            pass
        self._carrier_off()

    def is_busy(self) -> bool:
        return bool(self.pi.wave_tx_busy())

    # ---------- internals ----------

    def _carrier_on(self) -> None:
        self.pi.hardware_PWM(self.carrier_gpio, self.carrier_freq_hz, _HARDWARE_PWM_DUTY_50)

    def _carrier_off(self) -> None:
        self.pi.hardware_PWM(self.carrier_gpio, 0, 0)
        self.pi.write(self.carrier_gpio, 0)

    def _build_frame_wave(self, data: bytes) -> int:
        gate_mask = 1 << self.gate_gpio
        pulses: List[pigpio.pulse] = []
        for byte in data:
            cur = byte
            for _ in range(4):
                symbol = cur & 0x03
                cur >>= 2
                pulses.append(pigpio.pulse(gate_mask, 0, BURST_US))
                pulses.append(pigpio.pulse(0, gate_mask, GAP_US_BY_SYMBOL[symbol]))
        # Final closing burst (matches send_frame_pp4 in the C source).
        pulses.append(pigpio.pulse(gate_mask, 0, BURST_US))
        pulses.append(pigpio.pulse(0, gate_mask, 50))

        self.pi.wave_add_generic(pulses)
        wid = self.pi.wave_create()
        if wid < 0:
            raise TagTinkerIRError(f"pigpio wave_create failed: {wid}")
        return wid
