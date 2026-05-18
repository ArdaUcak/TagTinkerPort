# TagTinkerPort — Quick Start

## 1. Parts (~$5 + an ESL tag)

IR LED 940 nm, NPN transistor (2N3904 / 2N2222), 100 Ω resistor, 1 kΩ resistor, breadboard + jumpers.

## 2. Flash the Pi

Pi Imager → Raspberry Pi OS Lite (64-bit) → advanced options: set Wi-Fi + enable SSH.

## 3. On the Pi

```bash
sudo apt update && sudo apt install -y pigpio python3-pigpio python3-pil
sudo systemctl enable --now pigpiod
```

## 4. Get the code onto the Pi

```bash
sudo apt install -y git
git clone https://github.com/ArdaUcak/TagTinkerPort.git
cd TagTinkerPort
```

## 5. Wire it up

```
GPIO 18 (pin 12) → 100 Ω → IR LED anode
                           IR LED cathode → transistor collector
GPIO 17 (pin 11) → 1 kΩ  → transistor base
                           transistor emitter → GND (pin 9)
```

See [`wiring.md`](wiring.md) for the full schematic.

## 6. Get your tag's barcode

Flip the tag over → read the 17-digit number off the back sticker.

## 7. Send something

```bash
cd ~/TagTinkerPort
python3 examples/test_offline.py                              # sanity check (no IR)
python3 examples/send_ping.py  <17-digit-barcode>             # wake the tag
python3 examples/send_text.py  <17-digit-barcode> "HELLO"     # text
python3 examples/send_image.py <17-digit-barcode> picture.png # image
```

Aim the LED at the tag from ~30 cm. First ping should make it react; text/image takes 10–60 s depending on display size.

## If it doesn't work

95% of cases are one of:

- **Dead tag battery** — swap the CR2450.
- **Wrong barcode digits** — re-read carefully, no spaces.
- **`pigpio daemon not running`** — `sudo systemctl start pigpiod`.
- **Garbled image** — bump `--data-repeats 10` and aim more carefully at the tag's IR receiver window.
