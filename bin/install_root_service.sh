#!/usr/bin/env bash
set -euo pipefail

PLUGIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UNIT_NAME="hanauta-wireguard-autoconnect.service"
UNIT_SRC="$PLUGIN_DIR/systemd/$UNIT_NAME"
UNIT_DST="/etc/systemd/system/$UNIT_NAME"
CONF_DST="/etc/hanauta-wireguard-autoconnect.conf"

if [ ! -f "$UNIT_SRC" ]; then
  echo "Missing unit file: $UNIT_SRC" >&2
  exit 2
fi
if ! command -v systemctl >/dev/null 2>&1; then
  echo "systemctl is required." >&2
  exit 3
fi
if ! command -v wg-quick >/dev/null 2>&1; then
  echo "wg-quick is required (wireguard-tools)." >&2
  exit 4
fi

install -D -m 0644 "$UNIT_SRC" "$UNIT_DST"

if [ ! -f "$CONF_DST" ]; then
  iface="$(python3 - <<PY
import json
import os
import pwd
from pathlib import Path

iface = ""
uid_text = str(os.environ.get("PKEXEC_UID", "")).strip()
if uid_text.isdigit():
    try:
        home = Path(pwd.getpwuid(int(uid_text)).pw_dir)
        settings = home / ".local" / "state" / "hanauta" / "notification-center" / "settings.json"
        if settings.exists():
            payload = json.loads(settings.read_text(encoding="utf-8"))
            services = payload.get("services", {}) if isinstance(payload, dict) else {}
            vpn = services.get("vpn_control", {}) if isinstance(services, dict) else {}
            iface = str(vpn.get("preferred_interface", "")).strip()
    except Exception:
        iface = ""
print(iface)
PY
)"
  iface="${iface:-wg0}"
  printf "WG_IFACE=%s\n" "$iface" > "$CONF_DST"
  chmod 0644 "$CONF_DST"
fi

systemctl daemon-reload
systemctl reset-failed "$UNIT_NAME" >/dev/null 2>&1 || true
systemctl enable --now "$UNIT_NAME"

systemctl is-active --quiet "$UNIT_NAME"

echo "Installed and enabled: $UNIT_NAME"
