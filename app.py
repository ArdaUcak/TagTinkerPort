#!/usr/bin/env python3
"""Web UI for TagTinker — upload a photo from your phone, send it to a tag."""
from __future__ import annotations

import fcntl
import json
import os
import pwd
import shutil
import socket
import subprocess
import tempfile
import threading

from flask import Flask, jsonify, request

from tagtinker import (
    barcode_to_plid,
    barcode_to_profile,
    encode_planes_payload,
    is_addressable_barcode,
    is_barcode_valid,
)
from tagtinker.profiles import TagKind
from tagtinker.render import image_to_pixels
from tagtinker.sequence import send_full_image

# Imported at module top so a missing pigpio surfaces at startup rather than
# the first /send. The pigpio Python package is pure Python and importing it
# without a running daemon is fine; we only fail when the daemon's actually
# needed.
import pigpio
from tagtinker.ir import TagTinkerIR

app = Flask(__name__)
# Caps the in-memory image upload to something a 512 MB Pi can survive. The
# tag's actual payload is tiny — at 800x480 monochrome it's <50 KB on the
# wire — so 8 MB is plenty of headroom for camera JPEGs.
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024

HERE = os.path.dirname(os.path.abspath(__file__))
TAGS_FILE = os.path.join(HERE, "tags.json")
CREDENTIALS_FILE = os.path.join(HERE, "hotspot.credentials")
HOSTAPD_CONF = "/etc/hostapd/hostapd.conf"

_lock = threading.Lock()
_tags_file_lock = threading.Lock()
_wifi_file_lock = threading.Lock()
_status: dict = {"busy": False, "message": "Ready", "ok": None}


# ---------- tag storage ----------

def _load_tags() -> dict:
    with _tags_file_lock:
        if not os.path.exists(TAGS_FILE):
            return {}
        with open(TAGS_FILE) as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_SH)
            try:
                return json.load(f)
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def _save_tags(tags: dict) -> None:
    with _tags_file_lock:
        # Write to a sibling temp file then atomically rename so a crash
        # mid-write doesn't truncate tags.json.
        tmp_path = TAGS_FILE + ".tmp"
        with open(tmp_path, "w") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                json.dump(tags, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        os.replace(tmp_path, TAGS_FILE)


# ---------- Wi-Fi credentials ----------

def _load_wifi_info() -> dict | None:
    """Read hotspot.credentials. Returns None if it doesn't exist."""
    with _wifi_file_lock:
        if not os.path.exists(CREDENTIALS_FILE):
            return None
        info: dict[str, str] = {}
        try:
            with open(CREDENTIALS_FILE) as f:
                for line in f:
                    line = line.strip()
                    if "=" in line and not line.startswith("#"):
                        k, v = line.split("=", 1)
                        info[k.strip()] = v
        except OSError:
            return None
        return info if "ssid" in info else None


def _save_wifi_info(info: dict) -> None:
    with _wifi_file_lock:
        tmp = CREDENTIALS_FILE + ".tmp"
        with open(tmp, "w") as f:
            for k in ("ssid", "password", "ip"):
                if k in info:
                    f.write(f"{k}={info[k]}\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, CREDENTIALS_FILE)


def _network_manager_active() -> bool:
    if shutil.which("systemctl") is None:
        return False
    try:
        result = subprocess.run(
            ["systemctl", "is-active", "NetworkManager"],
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip() == "active"
    except (subprocess.SubprocessError, OSError):
        return False


def _apply_wifi_password(ssid: str, new_password: str) -> None:
    """Persist the new PSK to the live config (nmcli or hostapd.conf).

    Does NOT restart the radio — caller is expected to schedule that
    after returning a response, so the browser has a chance to see the
    success message before the connection drops.
    """
    if _network_manager_active():
        if shutil.which("nmcli") is None:
            raise RuntimeError("nmcli not found")
        subprocess.run(
            ["nmcli", "connection", "modify", ssid, "wifi-sec.psk", new_password],
            check=True, capture_output=True, text=True, timeout=10,
        )
        return

    # hostapd path: rewrite wpa_passphrase= line in place.
    if not os.path.exists(HOSTAPD_CONF):
        raise RuntimeError(
            "hostapd.conf not found and NetworkManager is not active — "
            "run setup_hotspot.sh first"
        )
    with open(HOSTAPD_CONF) as f:
        lines = f.readlines()
    new_lines = []
    replaced = False
    for line in lines:
        if line.lstrip().startswith("wpa_passphrase="):
            new_lines.append(f"wpa_passphrase={new_password}\n")
            replaced = True
        else:
            new_lines.append(line)
    if not replaced:
        new_lines.append(f"wpa_passphrase={new_password}\n")

    tmp = HOSTAPD_CONF + ".tmp"
    with open(tmp, "w") as f:
        f.writelines(new_lines)
    os.chmod(tmp, 0o600)
    os.replace(tmp, HOSTAPD_CONF)


def _restart_wifi(ssid: str) -> None:
    """Re-activate the AP so the new password takes effect."""
    if _network_manager_active():
        subprocess.run(
            ["nmcli", "connection", "up", ssid],
            check=False, capture_output=True, text=True, timeout=15,
        )
    else:
        subprocess.run(
            ["systemctl", "restart", "hostapd"],
            check=False, capture_output=True, text=True, timeout=15,
        )


# ---------- client-mode switching ----------

def _list_wifi_connection_names() -> list[str]:
    """All 802-11-wireless NM connection names, in NM's order."""
    if shutil.which("nmcli") is None:
        return []
    try:
        result = subprocess.run(
            ["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show"],
            capture_output=True, text=True, timeout=5, check=True,
        )
    except (subprocess.SubprocessError, OSError):
        return []
    names = []
    for line in result.stdout.splitlines():
        # -t output is colon-separated; nmcli escapes literal colons in
        # values as "\:". rpartition gets us TYPE off the end safely.
        head, sep, ctype = line.rpartition(":")
        if not sep:
            continue
        if ctype == "802-11-wireless":
            names.append(head.replace("\\:", ":"))
    return names


def _connection_field(name: str, field: str) -> str | None:
    """Single NM connection field via nmcli, or None if it can't be read."""
    try:
        result = subprocess.run(
            ["nmcli", "-t", "-f", field, "connection", "show", name],
            capture_output=True, text=True, timeout=5, check=True,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    for line in result.stdout.splitlines():
        _, sep, val = line.partition(":")
        if sep:
            return val
    return None


def _find_client_wifi() -> dict | None:
    """Locate a non-AP Wi-Fi connection saved on the Pi.

    On Bookworm Pi OS, the Pi-Imager-configured Wi-Fi is stored as an NM
    connection (usually named "preconfigured"). Returns {name, ssid} or
    None if no such connection exists.
    """
    info = _load_wifi_info()
    ap_name = info["ssid"] if info else None
    for name in _list_wifi_connection_names():
        if name == ap_name:
            continue
        mode = _connection_field(name, "802-11-wireless.mode") or ""
        if mode == "ap":
            continue
        ssid = _connection_field(name, "802-11-wireless.ssid") or name
        return {"name": name, "ssid": ssid}
    return None


def _ssh_user() -> str:
    """The likely SSH login user — first UID-1000 account, falling back to 'pi'."""
    try:
        return pwd.getpwuid(1000).pw_name
    except KeyError:
        return "pi"


def _switch_to_client(client_name: str, ap_name: str) -> None:
    """Drop the AP and bring up the client connection. Fire-and-forget."""
    subprocess.run(
        ["nmcli", "connection", "down", ap_name],
        check=False, capture_output=True, text=True, timeout=15,
    )
    subprocess.run(
        ["nmcli", "connection", "up", client_name],
        check=False, capture_output=True, text=True, timeout=30,
    )


# ---------- routes ----------

@app.route("/")
def index():
    return HTML


@app.route("/tags", methods=["GET"])
def list_tags():
    tags = _load_tags()
    out = []
    for name, barcode in tags.items():
        profile = barcode_to_profile(barcode)
        out.append({
            "name": name,
            "barcode": barcode,
            "model": profile.model_name if profile else "unknown",
            "size": f"{profile.width}x{profile.height}" if profile else "?",
        })
    return jsonify(out)


@app.route("/tags", methods=["POST"])
def add_tag():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    barcode = (data.get("barcode") or "").strip()

    if not name:
        return jsonify({"ok": False, "error": "Name is required"}), 400
    if len(name) > 64:
        return jsonify({"ok": False, "error": "Name is too long (max 64 chars)"}), 400
    if not is_barcode_valid(barcode):
        return jsonify({"ok": False, "error": "Barcode must be exactly 17 digits"}), 400
    if not is_addressable_barcode(barcode):
        return jsonify({"ok": False, "error": "Barcode decodes to the broadcast address — re-read the sticker"}), 400

    profile = barcode_to_profile(barcode)
    if not profile:
        return jsonify({"ok": False, "error": f"Type code {barcode[12:16]} not in profile table — unknown tag"}), 400
    if profile.kind != TagKind.DOT_MATRIX or profile.width == 0:
        return jsonify({"ok": False, "error": f"{profile.model_name} is a segment display — can't show photos"}), 400

    tags = _load_tags()
    tags[name] = barcode
    _save_tags(tags)
    return jsonify({"ok": True, "model": profile.model_name, "size": f"{profile.width}x{profile.height}"})


@app.route("/tags/<name>", methods=["DELETE"])
def delete_tag(name: str):
    tags = _load_tags()
    tags.pop(name, None)
    _save_tags(tags)
    return jsonify({"ok": True})


@app.route("/status")
def status():
    return jsonify(_status)


@app.route("/wifi", methods=["GET"])
def wifi_info():
    info = _load_wifi_info()
    if info is None:
        return jsonify({
            "configured": False,
            "error": "Hotspot not configured — run setup_hotspot.sh first",
        })
    return jsonify({
        "configured": True,
        "ssid": info.get("ssid", ""),
        "ip": info.get("ip", ""),
    })


def _validate_password(pw: str) -> str | None:
    if not isinstance(pw, str):
        return "Password is required"
    if len(pw) < 8 or len(pw) > 63:
        return "Password must be 8-63 characters (WPA2 requirement)"
    if any(ord(c) < 32 or ord(c) > 126 for c in pw):
        return "Password must be printable ASCII only"
    return None


@app.route("/wifi/password", methods=["POST"])
def wifi_password():
    data = request.get_json(silent=True) or {}
    new_password = data.get("password", "")

    err = _validate_password(new_password)
    if err:
        return jsonify({"ok": False, "error": err}), 400

    info = _load_wifi_info()
    if info is None:
        return jsonify({"ok": False, "error": "Hotspot not configured — run setup_hotspot.sh first"}), 400

    ssid = info["ssid"]
    try:
        _apply_wifi_password(ssid, new_password)
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        return jsonify({"ok": False, "error": f"Apply failed: {stderr or exc}"}), 500
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500

    info["password"] = new_password
    _save_wifi_info(info)

    # Delay the restart so this response can flush before the radio kicks
    # everyone off. 2 s is enough for a LAN HTTP round-trip on a Pi Zero.
    threading.Timer(2.0, _restart_wifi, args=(ssid,)).start()

    return jsonify({
        "ok": True,
        "message": (
            f"Password changed. Wi-Fi will restart in 2 seconds — "
            f"reconnect to '{ssid}' with the new password."
        ),
    })


@app.route("/wifi/client-info", methods=["GET"])
def wifi_client_info():
    info = _load_wifi_info()
    if info is None:
        return jsonify({
            "available": False,
            "error": "Hotspot not configured — run setup_hotspot.sh first",
        })
    if not _network_manager_active():
        return jsonify({
            "available": False,
            "error": "NetworkManager not active — client-mode switch requires NM",
        })
    client = _find_client_wifi()
    if client is None:
        return jsonify({
            "available": False,
            "error": (
                "No client Wi-Fi configured on this Pi. Re-flash with "
                "Pi Imager's Wi-Fi settings, or add an NM connection manually."
            ),
        })
    return jsonify({
        "available": True,
        "ssid": client["ssid"],
        "hostname": socket.gethostname(),
        "ssh_user": _ssh_user(),
        "ap_name": info["ssid"],
    })


@app.route("/wifi/mode", methods=["POST"])
def wifi_mode():
    data = request.get_json(silent=True) or {}
    mode = data.get("mode")
    if mode != "client":
        return jsonify({"ok": False, "error": "mode must be 'client'"}), 400
    if not _network_manager_active():
        return jsonify({"ok": False, "error": "NetworkManager not active"}), 400
    info = _load_wifi_info()
    if info is None:
        return jsonify({"ok": False, "error": "Hotspot not configured"}), 400
    client = _find_client_wifi()
    if client is None:
        return jsonify({"ok": False, "error": "No client Wi-Fi configured on this Pi"}), 400

    ap_name = info["ssid"]
    # Same 2 s delay trick as the password change — let the response flush
    # before we drop the AP and lock the browser out.
    threading.Timer(2.0, _switch_to_client, args=(client["name"], ap_name)).start()

    return jsonify({
        "ok": True,
        "message": (
            f"Switching in 2 seconds. The Pi will leave '{ap_name}' and "
            f"join '{client['ssid']}'. To get the hotspot back, ssh in "
            f"and run:  sudo nmcli connection up {ap_name}"
        ),
    })


@app.route("/send", methods=["POST"])
def send():
    global _status

    if not _lock.acquire(blocking=False):
        return jsonify({"ok": False, "error": "Already sending — wait for it to finish"}), 429

    try:
        tag_name = request.form.get("tag", "").strip()
        tags = _load_tags()
        if tag_name not in tags:
            return jsonify({"ok": False, "error": "Unknown tag"}), 400

        barcode = tags[tag_name]
        profile = barcode_to_profile(barcode)
        if not profile:
            return jsonify({"ok": False, "error": "Tag profile not found"}), 400

        file = request.files.get("image")
        if not file:
            return jsonify({"ok": False, "error": "No image uploaded"}), 400

        img_bytes = file.read()
        ext = os.path.splitext(file.filename or "img.jpg")[1] or ".jpg"
    except Exception:
        _lock.release()
        raise
    else:
        _status = {"busy": True, "message": "Rendering image...", "ok": None}
        threading.Thread(
            target=_send_worker,
            args=(barcode, profile, img_bytes, ext, tag_name),
            daemon=True,
        ).start()
        return jsonify({"ok": True})


def _send_worker(barcode, profile, img_bytes, ext, tag_name):
    global _status
    try:
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp.write(img_bytes)
            tmp_path = tmp.name

        try:
            pixels = image_to_pixels(tmp_path, profile.width, profile.height)
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

        payload = encode_planes_payload(pixels, None, mode="auto")
        plid = barcode_to_plid(barcode)

        _status["message"] = "Connecting to IR..."

        pi = pigpio.pi()
        if not pi.connected:
            _status = {"busy": False, "message": "pigpio daemon not running — run: sudo pigpiod -s 1", "ok": False}
            return

        ir = TagTinkerIR(pi)
        ir.init()
        _status["message"] = f"Sending to {tag_name}..."
        try:
            ok = send_full_image(ir, plid, payload, page=0, width=profile.width, height=profile.height)
        finally:
            ir.deinit()
            pi.stop()

        _status = {
            "busy": False,
            "message": "Done!" if ok else "Send failed — point the IR LED straight at the tag and try again",
            "ok": ok,
        }
    except Exception as exc:
        _status = {"busy": False, "message": f"Error: {exc}", "ok": False}
    finally:
        _lock.release()


# ---------- single-file HTML ----------

HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TagTinker</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,sans-serif;background:#0f0f0f;color:#eee;padding:16px;max-width:480px;margin:auto}
h1{font-size:1.5rem;font-weight:700;margin-bottom:20px}
h2{font-size:.85rem;text-transform:uppercase;letter-spacing:.08em;color:#666;margin-bottom:10px}
.card{background:#1a1a1a;border-radius:14px;padding:16px;margin-bottom:14px}
select,input[type=text],input[type=password]{width:100%;padding:11px 12px;border-radius:9px;border:1px solid #2a2a2a;background:#111;color:#eee;font-size:1rem;margin-bottom:10px;-webkit-appearance:none}
.wifi-meta{color:#888;font-size:.85rem;margin-bottom:10px;line-height:1.4}
.wifi-meta b{color:#ccc}
.show-pw{display:flex;align-items:center;gap:6px;color:#666;font-size:.8rem;margin-top:-4px;margin-bottom:10px;user-select:none;cursor:pointer}
.show-pw input{margin:0}
.drop{border:2px dashed #2a2a2a;border-radius:12px;padding:36px 16px;text-align:center;cursor:pointer;color:#555;font-size:.95rem;transition:border-color .15s;margin-bottom:10px;min-height:90px;display:flex;align-items:center;justify-content:center}
.drop.over{border-color:#555;color:#aaa}
.drop img{max-width:100%;max-height:220px;border-radius:8px;display:block}
.btn{width:100%;padding:14px;border-radius:11px;border:none;font-size:1rem;font-weight:600;cursor:pointer;transition:opacity .15s}
.btn-send{background:#2563eb;color:#fff}
.btn-add{background:#222;color:#ccc;margin-top:6px}
.btn:disabled{opacity:.35;cursor:default}
.status{padding:11px 14px;border-radius:9px;font-size:.9rem;margin-top:10px;display:none}
.status.busy{background:#0d2040;color:#60aeff}
.status.ok{background:#0d2a0d;color:#4ade80}
.status.err{background:#2a0d0d;color:#f87171}
.tag-row{display:flex;justify-content:space-between;align-items:center;padding:9px 0;border-bottom:1px solid #222}
.tag-row:last-child{border:none}
.tag-name{font-weight:600;font-size:.95rem}
.tag-meta{font-size:.78rem;color:#555;margin-top:2px}
.btn-del{background:#2a0d0d;color:#f87171;border:none;border-radius:6px;padding:4px 9px;font-size:.78rem;cursor:pointer;flex-shrink:0}
.toggle{font-size:.85rem;color:#555;cursor:pointer;user-select:none;margin-bottom:10px}
.hidden{display:none}
.divider{height:1px;background:#222;margin:18px 0 12px}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.85rem;color:#ccc;margin-top:4px;word-break:break-all}
</style>
</head>
<body>
<h1>TagTinker</h1>

<div class="card">
  <h2>Send a photo</h2>
  <select id="sel"><option value="">- pick a tag -</option></select>
  <div class="drop" id="drop">tap to pick a photo</div>
  <input type="file" id="file" accept="image/*" style="display:none">
  <button class="btn btn-send" id="sendBtn" disabled>Send</button>
  <div class="status" id="sendStatus"></div>
</div>

<div class="card">
  <div class="toggle" id="addToggle">+ Add a tag</div>
  <div class="hidden" id="addForm">
    <input type="text" id="addName" placeholder="Nickname (e.g. kitchen)" maxlength="64">
    <input type="text" id="addBarcode" placeholder="17-digit barcode" inputmode="numeric" maxlength="17">
    <button class="btn btn-add" id="addBtn">Add</button>
    <div class="status" id="addStatus"></div>
  </div>
</div>

<div class="card">
  <h2>My tags</h2>
  <div id="tagList"></div>
</div>

<div class="card">
  <h2>Wi-Fi</h2>
  <div class="wifi-meta" id="wifiMeta">Loading...</div>
  <input type="password" id="wifiNewPw" placeholder="New password (8-63 chars)" maxlength="63">
  <label class="show-pw"><input type="checkbox" id="wifiShow"> show password</label>
  <button class="btn btn-add" id="wifiSaveBtn">Change Wi-Fi password</button>
  <div class="status" id="wifiStatus"></div>

  <div class="divider"></div>
  <h2>Debug · SSH</h2>
  <div class="wifi-meta" id="clientMeta">Loading...</div>
  <button class="btn btn-add" id="clientSwitchBtn" disabled>Switch to client mode</button>
  <div class="status" id="clientStatus"></div>
</div>

<script>
let pickedFile = null, polling = null;

function el(tag, props) {
  const e = document.createElement(tag);
  if (props) {
    for (const k in props) {
      if (k === 'text') e.textContent = props[k];
      else if (k === 'children') props[k].forEach(c => e.appendChild(c));
      else e[k] = props[k];
    }
  }
  return e;
}

async function loadTags() {
  const tags = await fetch('/tags').then(r => r.json());
  const sel = document.getElementById('sel');
  const list = document.getElementById('tagList');

  // Rebuild select
  sel.textContent = '';
  sel.appendChild(el('option', {value: '', text: '- pick a tag -'}));
  tags.forEach(t => {
    sel.appendChild(el('option', {value: t.name, text: `${t.name} - ${t.model} (${t.size})`}));
  });

  // Rebuild list
  list.textContent = '';
  if (!tags.length) {
    list.appendChild(el('span', {text: 'No tags yet - add one above', style: 'color:#444;font-size:.9rem'}));
    checkReady();
    return;
  }
  tags.forEach(t => {
    const row = el('div', {className: 'tag-row'});
    const info = el('div');
    info.appendChild(el('div', {className: 'tag-name', text: t.name}));
    info.appendChild(el('div', {className: 'tag-meta', text: `${t.model} - ${t.size} - ${t.barcode}`}));
    row.appendChild(info);
    const del = el('button', {className: 'btn-del', text: 'X', onclick: () => delTag(t.name)});
    row.appendChild(del);
    list.appendChild(row);
  });
  checkReady();
}

async function delTag(name) {
  await fetch('/tags/' + encodeURIComponent(name), {method:'DELETE'});
  loadTags();
}

document.getElementById('addToggle').onclick = function() {
  const f = document.getElementById('addForm');
  f.classList.toggle('hidden');
  this.textContent = (f.classList.contains('hidden') ? '+' : '-') + ' Add a tag';
};

document.getElementById('addBtn').onclick = async () => {
  const name = document.getElementById('addName').value.trim();
  const barcode = document.getElementById('addBarcode').value.trim();
  const st = document.getElementById('addStatus');
  const res = await fetch('/tags', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({name, barcode})});
  const d = await res.json();
  showStatus(st, d.ok ? 'ok' : 'err', d.ok ? `Added! ${d.model} - ${d.size}` : d.error);
  if (d.ok) {
    document.getElementById('addName').value = '';
    document.getElementById('addBarcode').value = '';
    loadTags();
  }
};

const drop = document.getElementById('drop');
const fileInput = document.getElementById('file');
drop.onclick = () => fileInput.click();
drop.ondragover = e => { e.preventDefault(); drop.classList.add('over'); };
drop.ondragleave = () => drop.classList.remove('over');
drop.ondrop = e => { e.preventDefault(); drop.classList.remove('over'); setFile(e.dataTransfer.files[0]); };
fileInput.onchange = () => setFile(fileInput.files[0]);

function setFile(f) {
  if (!f) return;
  pickedFile = f;
  const r = new FileReader();
  r.onload = e => {
    drop.textContent = '';
    const img = el('img');
    img.src = e.target.result;
    drop.appendChild(img);
  };
  r.readAsDataURL(f);
  checkReady();
}

function checkReady() {
  document.getElementById('sendBtn').disabled = !(pickedFile && document.getElementById('sel').value);
}
document.getElementById('sel').onchange = checkReady;

document.getElementById('sendBtn').onclick = async () => {
  const fd = new FormData();
  fd.append('tag', document.getElementById('sel').value);
  fd.append('image', pickedFile);
  document.getElementById('sendBtn').disabled = true;
  const st = document.getElementById('sendStatus');
  showStatus(st, 'busy', 'Sending...');
  await fetch('/send', {method:'POST', body: fd});
  if (polling) clearInterval(polling);
  polling = setInterval(async () => {
    const s = await fetch('/status').then(r => r.json());
    showStatus(st, s.busy ? 'busy' : s.ok ? 'ok' : 'err', s.message);
    if (!s.busy) {
      clearInterval(polling); polling = null;
      checkReady();
    }
  }, 800);
};

function showStatus(el, type, msg) {
  el.className = 'status ' + type;
  el.textContent = msg;
  el.style.display = 'block';
}

// ---- Wi-Fi tab ----

async function loadWifi() {
  const meta = document.getElementById('wifiMeta');
  const saveBtn = document.getElementById('wifiSaveBtn');
  try {
    const w = await fetch('/wifi').then(r => r.json());
    meta.textContent = '';
    if (!w.configured) {
      meta.appendChild(el('span', {text: w.error || 'Hotspot not configured.'}));
      saveBtn.disabled = true;
      document.getElementById('wifiNewPw').disabled = true;
      return;
    }
    meta.appendChild(el('div', {children: [
      document.createTextNode('Network: '),
      el('b', {text: w.ssid}),
    ]}));
    if (w.ip) {
      meta.appendChild(el('div', {text: 'Address: http://' + w.ip}));
    }
    meta.appendChild(el('div', {
      text: 'Changing the password will kick all connected phones — you’ll have to reconnect with the new one.',
      style: 'color:#a06;margin-top:4px',
    }));
  } catch (e) {
    meta.textContent = 'Could not load Wi-Fi info.';
  }
}

document.getElementById('wifiShow').onchange = function() {
  document.getElementById('wifiNewPw').type = this.checked ? 'text' : 'password';
};

document.getElementById('wifiSaveBtn').onclick = async () => {
  const pw = document.getElementById('wifiNewPw').value;
  const st = document.getElementById('wifiStatus');
  if (pw.length < 8 || pw.length > 63) {
    showStatus(st, 'err', 'Password must be 8-63 characters.');
    return;
  }
  const btn = document.getElementById('wifiSaveBtn');
  btn.disabled = true;
  showStatus(st, 'busy', 'Saving...');
  try {
    const res = await fetch('/wifi/password', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({password: pw}),
    });
    const d = await res.json();
    if (d.ok) {
      showStatus(st, 'ok', d.message);
      document.getElementById('wifiNewPw').value = '';
    } else {
      showStatus(st, 'err', d.error || 'Failed.');
    }
  } catch (e) {
    showStatus(st, 'err', 'Request failed.');
  } finally {
    btn.disabled = false;
  }
};

// ---- Client-mode (SSH) switch ----

async function loadClientMode() {
  const meta = document.getElementById('clientMeta');
  const btn = document.getElementById('clientSwitchBtn');
  try {
    const w = await fetch('/wifi/client-info').then(r => r.json());
    meta.textContent = '';
    if (!w.available) {
      meta.appendChild(el('span', {text: w.error || 'Not available.'}));
      btn.disabled = true;
      return;
    }
    meta.appendChild(el('div', {children: [
      document.createTextNode('Will join: '),
      el('b', {text: w.ssid}),
    ]}));
    meta.appendChild(el('div', {className: 'mono', text: `ssh ${w.ssh_user}@${w.hostname}.local`}));
    meta.appendChild(el('div', {
      text: `To recover the hotspot, ssh in and run:  sudo nmcli connection up ${w.ap_name}`,
      style: 'color:#a06;margin-top:6px;font-size:.8rem',
    }));
    btn.disabled = false;
  } catch (e) {
    meta.textContent = 'Could not load client-mode info.';
    btn.disabled = true;
  }
}

document.getElementById('clientSwitchBtn').onclick = async () => {
  const st = document.getElementById('clientStatus');
  if (!confirm('Switch to client mode? You will lose this page.')) return;
  const btn = document.getElementById('clientSwitchBtn');
  btn.disabled = true;
  showStatus(st, 'busy', 'Switching...');
  try {
    const res = await fetch('/wifi/mode', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({mode: 'client'}),
    });
    const d = await res.json();
    if (d.ok) {
      showStatus(st, 'ok', d.message);
    } else {
      showStatus(st, 'err', d.error || 'Failed.');
      btn.disabled = false;
    }
  } catch (e) {
    showStatus(st, 'err', 'Request failed.');
    btn.disabled = false;
  }
};

loadTags();
loadWifi();
loadClientMode();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=80, debug=False)
