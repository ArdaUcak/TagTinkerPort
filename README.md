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
sudo apt install -y pigpio python3-pigpio python3-pil git
sudo systemctl enable --now pigpiod
```

**3. Run pigpiod at 1 µs sample rate** — the default 5 µs rounding garbles
the PP4 symbol gaps and some tags refuse to decode. Drop in an override:

```bash
sudo mkdir -p /etc/systemd/system/pigpiod.service.d
echo -e "[Service]\nExecStart=\nExecStart=/usr/bin/pigpiod -l -s 1" \
  | sudo tee /etc/systemd/system/pigpiod.service.d/override.conf
sudo systemctl daemon-reload && sudo systemctl restart pigpiod
```

**4. Free PWM0 from the audio driver.** Raspberry Pi OS binds PWM0/PWM1 to
the on-board audio by default, which conflicts with the IR carrier on
GPIO 18:

```bash
sudo sed -i 's/^dtparam=audio=on/dtparam=audio=off/' /boot/firmware/config.txt
sudo reboot
```

(If `/boot/firmware/config.txt` doesn't exist, try `/boot/config.txt` on
older Pi OS images.)

**5. Copy this folder onto the Pi.** Either `git clone` it on the Pi itself,
or from your local machine:

```bash
scp -r ./TagTinkerPort pi@<pi-ip>:~/
```

**6. Wire up the IR LED** — see [`wiring.md`](wiring.md) for the full
schematic and parts list. Five connections:

![Schematic](schematic.png)

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

## Optional: phone-friendly web UI

`app.py` is a single-file Flask app that lets you upload photos from your
phone and pick which tag to push them to. `setup_hotspot.sh` turns the Pi
into its own WPA2-protected Wi-Fi access point so you don't need a router:

```bash
sudo bash setup_hotspot.sh
sudo reboot
```

The script detects whether your Pi uses NetworkManager (Bookworm and newer)
or dhcpcd+hostapd (Bullseye and older) and configures the right one.

Default Wi-Fi password is **`12341234`** (WPA2 forbids the 4-char `1234`).
Change it from the **Wi-Fi tab** in the web UI once you're connected; the
new password takes effect after a 2-second delay so the browser can show
the confirmation before your phone gets kicked off.

The current credentials live in `hotspot.credentials` (root-readable only,
in the project folder). Connect your phone to the `TagTinker` SSID, then
open `http://192.168.4.1`.

## Troubleshooting

- **Tag doesn't respond to anything** — battery's probably dead. ESL tags use a
  CR2450 that often arrives flat on auction-lot units. Swap it.
- **`pigpio daemon not running`** — `sudo systemctl start pigpiod`.
- **`unknown tag type`** — your tag's type code isn't in `profiles.py`. Pass
  `--width` and `--height` explicitly, or add it to the profile table.
- **Tag wakes but image looks garbled** — most often a timing issue. Confirm
  `pigpiod` is running with `-s 1` (`ps ax | grep pigpiod`), then try
  `--data-repeats 10` for more transmission redundancy. Also check you're
  pointing straight at the IR receiver on the tag (a small dark window near
  the edge).
- **Carrier appears dead even though the gate pulses** — the audio driver is
  probably still holding PWM0. Re-check that `dtparam=audio=off` is in
  `/boot/firmware/config.txt` and reboot.

## What's in here

- `tagtinker/` — the library: protocol, IR driver, sequencing, rendering.
- `examples/` — runnable CLIs for ping / text / image.
- `wiring.md` + `schematic.png` — wiring schematic.

## What's not in here

NFC scanning, the Flipper UI, Wi-Fi cloud plugins, and segment-display
encoding. None of those are needed for sending an image to a dot-matrix tag.

## License

GPL-3.0, same as upstream.
