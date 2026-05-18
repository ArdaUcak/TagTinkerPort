#!/bin/bash
# Sets up the Pi as its own Wi-Fi hotspot.
# Run once after flashing: sudo bash setup_hotspot.sh
#
# Optional env vars:
#   SSID=TagTinker     hotspot name
#   PASSWORD=...       WPA2 password (8-63 chars). Defaults to "12341234" —
#                      WPA2 forbids shorter keys, so 4-char "1234" isn't an
#                      option. Change it from the web UI's Wi-Fi tab after
#                      first boot.
#   COUNTRY=US         ISO country code for regulatory domain
#   CHANNEL=6          2.4 GHz channel
#
# Your phone connects to the "TagTinker" network with the printed password,
# then opens http://192.168.4.1 in a browser.

set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "Run as root: sudo bash $0" >&2
    exit 1
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SSID="${SSID:-TagTinker}"
IP="192.168.4.1"
COUNTRY="${COUNTRY:-US}"
CHANNEL="${CHANNEL:-6}"
CRED_FILE="${SCRIPT_DIR}/hotspot.credentials"

if [ -z "${PASSWORD:-}" ]; then
    if [ -r "${CRED_FILE}" ]; then
        # Re-use the existing password on re-runs so already-paired phones
        # don't get locked out.
        PASSWORD="$(awk -F= '/^password=/{print $2; exit}' "${CRED_FILE}")"
    fi
fi
if [ -z "${PASSWORD:-}" ]; then
    PASSWORD="12341234"
fi
if [ "${#PASSWORD}" -lt 8 ] || [ "${#PASSWORD}" -gt 63 ]; then
    echo "PASSWORD must be 8-63 characters (got ${#PASSWORD})" >&2
    exit 1
fi

# --- detect network stack -------------------------------------------------
USE_NM=0
if systemctl list-unit-files 2>/dev/null | grep -q '^NetworkManager\.service' \
    && systemctl is-active --quiet NetworkManager 2>/dev/null; then
    USE_NM=1
fi

# --- pigpiod with 1 µs sample rate ----------------------------------------
# The PP4 symbol gaps include 121 and 181 µs values; the default 5 µs sample
# rate rounds them to 120/180, which some tags refuse to decode. Drop in an
# override that pins the daemon to -s 1.
echo "Configuring pigpiod for 1 us sample rate..."
mkdir -p /etc/systemd/system/pigpiod.service.d
cat > /etc/systemd/system/pigpiod.service.d/override.conf <<'EOF'
[Service]
ExecStart=
ExecStart=/usr/bin/pigpiod -l -s 1
EOF
systemctl daemon-reload
systemctl enable pigpiod >/dev/null 2>&1 || true
systemctl restart pigpiod || true

# --- ensure runtime country code ------------------------------------------
# Some firmwares refuse to bring up the AP without a regulatory domain.
if command -v raspi-config >/dev/null 2>&1; then
    raspi-config nonint do_wifi_country "${COUNTRY}" || true
fi

if [ "${USE_NM}" -eq 1 ]; then
    echo "NetworkManager is active — configuring hotspot via nmcli..."
    apt-get update -qq
    # NetworkManager already provides hostapd/dnsmasq functionality.

    # Wipe any prior connection of the same name so re-runs are idempotent.
    nmcli connection delete "${SSID}" >/dev/null 2>&1 || true

    nmcli connection add type wifi ifname wlan0 con-name "${SSID}" \
        autoconnect yes ssid "${SSID}"
    nmcli connection modify "${SSID}" \
        802-11-wireless.mode ap \
        802-11-wireless.band bg \
        802-11-wireless.channel "${CHANNEL}" \
        ipv4.method shared \
        ipv4.addresses "${IP}/24" \
        ipv6.method disabled \
        wifi-sec.key-mgmt wpa-psk \
        wifi-sec.proto rsn \
        wifi-sec.pairwise ccmp \
        wifi-sec.group ccmp \
        wifi-sec.psk "${PASSWORD}"
    nmcli connection up "${SSID}" >/dev/null 2>&1 || true
else
    echo "NetworkManager not detected — falling back to hostapd + dnsmasq..."
    apt-get update -qq
    apt-get install -y hostapd dnsmasq

    # dhcpcd static IP (idempotent — only append if our marker is absent).
    DHCPCD_MARKER="# >>> tagtinker hotspot >>>"
    if ! grep -qF "${DHCPCD_MARKER}" /etc/dhcpcd.conf 2>/dev/null; then
        cat >> /etc/dhcpcd.conf <<EOF

${DHCPCD_MARKER}
interface wlan0
    static ip_address=${IP}/24
    nohook wpa_supplicant
# <<< tagtinker hotspot <<<
EOF
    fi

    # dnsmasq: only back up the original once (don't blow it away on re-run).
    if [ -f /etc/dnsmasq.conf ] && [ ! -f /etc/dnsmasq.conf.bak ]; then
        mv /etc/dnsmasq.conf /etc/dnsmasq.conf.bak
    fi
    cat > /etc/dnsmasq.conf <<EOF
interface=wlan0
dhcp-range=192.168.4.2,192.168.4.20,255.255.255.0,24h
EOF

    cat > /etc/hostapd/hostapd.conf <<EOF
interface=wlan0
driver=nl80211
ssid=${SSID}
country_code=${COUNTRY}
hw_mode=g
channel=${CHANNEL}
wmm_enabled=1
auth_algs=1
ignore_broadcast_ssid=0
wpa=2
wpa_key_mgmt=WPA-PSK
wpa_pairwise=CCMP
rsn_pairwise=CCMP
wpa_passphrase=${PASSWORD}
EOF
    chmod 600 /etc/hostapd/hostapd.conf

    sed -i 's|^#\?DAEMON_CONF=.*|DAEMON_CONF="/etc/hostapd/hostapd.conf"|' /etc/default/hostapd

    systemctl unmask hostapd
    systemctl enable hostapd
    systemctl enable dnsmasq
fi

# --- Python deps -----------------------------------------------------------
echo "Installing Python deps..."
# python3-pigpio + python3-pil come from apt (matches QUICKSTART). Flask we
# pull from pip because Bookworm only has flask 2.x and we use Flask 3.x
# features. --break-system-packages is required on PEP 668-managed Pythons.
apt-get install -y python3-pigpio python3-pil
pip3 install --break-system-packages 'flask>=3.0' 2>/dev/null \
    || pip3 install 'flask>=3.0'

# --- TagTinker service -----------------------------------------------------
echo "Installing TagTinker service from ${SCRIPT_DIR}..."
cat > /etc/systemd/system/tagtinker.service <<EOF
[Unit]
Description=TagTinker Web UI
After=network.target pigpiod.service
Requires=pigpiod.service

[Service]
ExecStart=/usr/bin/python3 ${SCRIPT_DIR}/app.py
WorkingDirectory=${SCRIPT_DIR}
Restart=always
User=root

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable tagtinker

# --- save + print credentials ---------------------------------------------
umask 077
cat > "${CRED_FILE}" <<EOF
ssid=${SSID}
password=${PASSWORD}
ip=${IP}
EOF
chmod 600 "${CRED_FILE}"

echo ""
echo "================================================================"
echo "  Done. Reboot the Pi, then:"
echo "    1. Connect your phone to Wi-Fi:"
echo "         SSID:     ${SSID}"
echo "         Password: ${PASSWORD}"
echo "    2. Open http://${IP} in your browser"
echo ""
echo "  Credentials also saved to: ${CRED_FILE}"
echo "================================================================"
