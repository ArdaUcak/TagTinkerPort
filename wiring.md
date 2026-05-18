# Wiring — Pi Zero 2W → IR LED

The Pi can't gate its hardware PWM cleanly from software at microsecond
resolution, so we use two GPIO pins ANDed by a single NPN transistor:

- **GPIO 18 (PWM0)** — `carrier_gpio`. Hardware PWM, 1.255 MHz, ~50 % duty.
  Sources the LED current. (Pin **12** on the 40-pin header.)
- **GPIO 17** — `gate_gpio`. DMA waveform that drives the transistor base
  HIGH during a 40 µs burst and LOW during the gap. (Pin **11**.)

## Schematic (single NPN transistor, ~3 parts)

```
                  +---------- GPIO 18 (pin 12, BCM 18) — carrier PWM @ 1.255 MHz
                  |
                  R1 = 100 Ω    (current-limit for the IR LED, ~20 mA peak)
                  |
                  =  IR LED   (anode top, cathode bottom)
                  |
                  +-------+
                          |
                          C (collector)
                          |
                         |/
                  Q1 ----| 2N3904 / 2N2222 / BC547   (any small-signal NPN)
                         |\
                          |
                          E (emitter)
                          |
                         GND
                          ^
                          |
                          R2 = 1 kΩ ───── GPIO 17 (pin 11, BCM 17) — gate
                                          (R2 sits between GPIO 17 and the base)
```

**Why this works:**
- When *gate* is LOW, Q1 is off and the LED sees no path to ground → no light.
- When *gate* is HIGH, Q1 saturates and the LED is free to conduct current
  driven by the PWM carrier on GPIO 18.
- The carrier toggles ~1.255 million times per second, lighting the LED in
  bursts that match the Flipper's symbol timing.

## Header pin reference

```
Pin 11 = BCM 17 (gate)        Pin 12 = BCM 18 (carrier / PWM0)
Pin 9  = GND                  Pin 6  = GND     (use whichever is convenient)
```

## Parts list

| Part   | Value     | Notes                                              |
|--------|-----------|----------------------------------------------------|
| Q1     | 2N3904    | Any general-purpose NPN works (2N2222, BC547, …)   |
| R1     | 100 Ω     | Current limit. Bump to 220 Ω for less LED current. |
| R2     | 1 kΩ      | Base resistor. 470 Ω – 10 kΩ all fine.             |
| LED    | IR 940 nm | A 5 mm IR LED with ~20 mA forward current works.   |

## Notes

- The Flipper outputs ~3.3 V on its IR pin too, so this circuit
  reproduces the same drive level. The IR LED is in a single-pulse path,
  no booster needed for short range.
- If you want more range, replace R1 with ~22 Ω and use a 5 V supply
  through an additional high-side PNP/PMOS driven by GPIO 18 — but
  3.3 V direct drive is plenty for ESL tags within ~30 cm.
- Keep wires short. The 1.255 MHz carrier has fast edges and long flying
  leads will ring.

## Alternative pin choices

`hardware_PWM` on pigpio supports BCM **12, 13, 18, 19**. If GPIO 18 is in
use by audio or another peripheral, you can pass `--carrier-gpio 12`
(pin 32) to the example scripts. The gate pin can be any free GPIO; pass
`--gate-gpio <n>` to override.
