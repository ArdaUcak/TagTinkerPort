# TagTinkerPort — Quick Start

## 1. Parts (~$5 + an ESL tag)

IR LED 940 nm, NPN transistor (2N3904 / 2N2222), 100 Ω resistor, 1 kΩ resistor, breadboard + jumpers.

## 2. Flash the Pi

Pi Imager → Raspberry Pi OS Lite (64-bit) → advanced options: set Wi-Fi + enable SSH.

## 3. On the Pi

```bash
sudo apt update && sudo apt install -y pigpio python3-pigpio python3-pil git

# pigpiod must run at 1 µs sample rate or the PP4 symbol gaps get rounded
# off and the tag refuses to decode.
sudo mkdir -p /etc/systemd/system/pigpiod.service.d
echo -e "[Service]\nExecStart=\nExecStart=/usr/bin/pigpiod -l -s 1" \
  | sudo tee /etc/systemd/system/pigpiod.service.d/override.conf
sudo systemctl daemon-reload && sudo systemctl enable --now pigpiod

# Free PWM0 from the audio driver, then reboot.
sudo sed -i 's/^dtparam=audio=on/dtparam=audio=off/' /boot/firmware/config.txt
sudo reboot
```

## 4. Get the code onto the Pi

```bash
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
- **`pigpiod` running without `-s 1`** — check `ps ax | grep pigpiod`; if you
  don't see `-s 1` in the command line, the symbol gaps are being quantized
  to 5 µs steps and the tag may not decode.
- **PWM0 still bound to audio** — verify `/boot/firmware/config.txt` has
  `dtparam=audio=off` (or `dtoverlay=...,noaudio` etc.) and reboot.
- **Garbled image** — bump `--data-repeats 10` and aim more carefully at the tag's IR receiver window.

## Optional: web UI + Wi-Fi hotspot

```bash
sudo bash setup_hotspot.sh
sudo reboot
```

The Pi will come back up as a WPA2-protected `TagTinker` access point.
Default password is **`12341234`**. Connect your phone, open
`http://192.168.4.1`, and use the **Wi-Fi tab** to change the password to
whatever you want (8-63 chars).
