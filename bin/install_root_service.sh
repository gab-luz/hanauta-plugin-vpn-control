#!/usr/bin/env bash
set -euo pipefail

PLUGIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UNIT_NAME="hanauta-wireguard-autoconnect.service"
AGENT_UNIT_NAME="hanauta-wireguard-agent.service"
UNIT_SRC="$PLUGIN_DIR/systemd/$UNIT_NAME"
AGENT_UNIT_SRC="$PLUGIN_DIR/systemd/$AGENT_UNIT_NAME"
UNIT_DST="/etc/systemd/system/$UNIT_NAME"
AGENT_UNIT_DST="/etc/systemd/system/$AGENT_UNIT_NAME"
CONF_DST="/etc/hanauta-wireguard-autoconnect.conf"
AGENT_DIR="/usr/local/lib/hanauta-plugin-vpn-control"
AGENT_SCRIPT_SRC="$PLUGIN_DIR/root_wireguard_agent.py"
AGENT_SCRIPT_DST="$AGENT_DIR/root_wireguard_agent.py"

if [ ! -f "$UNIT_SRC" ]; then
  echo "Missing unit file: $UNIT_SRC" >&2
  exit 2
fi
if [ ! -f "$AGENT_UNIT_SRC" ]; then
  echo "Missing unit file: $AGENT_UNIT_SRC" >&2
  exit 2
fi
if [ ! -f "$AGENT_SCRIPT_SRC" ]; then
  echo "Missing script: $AGENT_SCRIPT_SRC" >&2
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
install -D -m 0755 "$AGENT_SCRIPT_SRC" "$AGENT_SCRIPT_DST"
sed "s|@AGENT_SCRIPT@|$AGENT_SCRIPT_DST|g" "$AGENT_UNIT_SRC" > "$AGENT_UNIT_DST"

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
  user_home="$(python3 - <<PY
import os
import pwd
uid_text = str(os.environ.get("PKEXEC_UID", "")).strip()
if uid_text.isdigit():
    try:
        print(pwd.getpwuid(int(uid_text)).pw_dir)
    except Exception:
        pass
PY
)"
  user_home="${user_home:-$HOME}"
  printf "WG_IFACE=%s\nHANAUTA_USER_HOME=%s\n" "$iface" "$user_home" > "$CONF_DST"
  chmod 0644 "$CONF_DST"
fi

systemctl daemon-reload
systemctl reset-failed "$UNIT_NAME" >/dev/null 2>&1 || true
systemctl enable --now "$UNIT_NAME"
systemctl reset-failed "$AGENT_UNIT_NAME" >/dev/null 2>&1 || true
systemctl enable --now "$AGENT_UNIT_NAME"

systemctl is-active --quiet "$UNIT_NAME"
systemctl is-active --quiet "$AGENT_UNIT_NAME"

echo "Installed and enabled: $UNIT_NAME, $AGENT_UNIT_NAME"
