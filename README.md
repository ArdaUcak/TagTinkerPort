# TagTinkerPort

A Raspberry Pi port of [TagTinker](https://github.com/i12bp8/TagTinker) — sends
images and text to infrared electronic shelf labels (ESL) using `pigpio` instead
of the Flipper Zero's hardware.

## What you need

### Hardware (~$5 plus the tag)

| Part | Notes |
|---|---|
| Raspberry Pi Zero 2W | Or any Pi with the 40-pin header. |
| microSD card, 5 V supply | Standard Pi stuff. |
| IR LED, 940 nm | 5 mm through-hole. |
| NPN transistor | 2N3904, 2N2222, or BC547. |
| 100 Ω resistor | Current limit for the LED. |
| 1 kΩ resistor | Base resistor. |
| Breadboard + jumpers | Or solder it on protoboard. |
| **An ESL tag** | The hard part — not sold retail. Look for SES-imagotag / VusionGroup tags on eBay or AliExpress. Must be **dot-matrix** (anything starting with `DM` or `SmartTag HD` in [`tagtinker/profiles.py`](tagtinker/profiles.py)), not a segment LCD. |

### The tag's 17-digit barcode

Flip the tag over — the barcode is on a sticker on the back. Type those 17
digits with no spaces.

## Setup

**1. Flash Raspberry Pi OS Lite** to the SD card with Pi Imager. In the imager's
advanced options, set Wi-Fi and enable SSH.

**2. SSH in and install dependencies:**

```bash
sudo apt update
sudo apt install -y pigpio python3-pigpio python3-pil
sudo systemctl enable --now pigpiod
```

**3. Copy this folder onto the Pi** (from your Windows machine):

```powershell
scp -r "C:\Users\horse\OneDrive\Masaüstü\TagTinkerPort" pi@<pi-ip>:~/
```

**4. Wire up the IR LED** — see [`wiring.md`](wiring.md). Five connections:

```
Pi pin 12 (GPIO 18) ── 100 Ω ── IR LED anode
                                IR LED cathode ── transistor collector
Pi pin 11 (GPIO 17) ── 1 kΩ  ── transistor base
                                transistor emitter ── Pi pin 9 (GND)
```

## Run it

```bash
cd ~/TagTinkerPort

# sanity check, no hardware needed
python3 examples/test_offline.py

# real transmissions — replace with your tag's actual barcode
python3 examples/send_ping.py  21099601234567890
python3 examples/send_text.py  21099601234567890 "HELLO"
python3 examples/send_image.py 21099601234567890 logo.png
```

Point the IR LED at the tag from within ~30 cm.

## Troubleshooting

- **Tag doesn't respond to anything** — battery's probably dead. ESL tags use a
  CR2450 that often arrives flat on auction-lot units. Swap it.
- **`pigpio daemon not running`** — `sudo systemctl start pigpiod`.
- **`unknown tag type`** — your tag's type code isn't in `profiles.py`. Pass
  `--width` and `--height` explicitly, or add it to the profile table.
- **Tag wakes but image looks garbled** — try `--data-repeats 10` for more
  reliable transmission, and check you're pointing straight at the IR receiver
  on the tag (usually a small dark window near the edge).

## What's in here

- `tagtinker/` — the library: protocol, IR driver, sequencing, rendering.
- `examples/` — runnable CLIs for ping / text / image.
- `wiring.md` — schematic.

## What's not in here

NFC scanning, the Flipper UI, Wi-Fi cloud plugins, and segment-display
encoding. None of those are needed for sending an image to a dot-matrix tag.

## License

GPL-3.0, same as upstream.
