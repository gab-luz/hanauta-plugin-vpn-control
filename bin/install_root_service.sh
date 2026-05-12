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

# Always keep HANAUTA_USER_HOME updated and preserve existing WG_IFACE when present.
python3 - <<PY
from pathlib import Path
conf = Path("$CONF_DST")
iface = "$iface".strip() or "wg0"
home = "$user_home".strip()
data = {}
if conf.exists():
    for line in conf.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        data[k.strip()] = v.strip()
data["WG_IFACE"] = data.get("WG_IFACE", iface) or iface
data["HANAUTA_USER_HOME"] = home
conf.write_text(
    "WG_IFACE={}\\nHANAUTA_USER_HOME={}\\n".format(
        data["WG_IFACE"], data["HANAUTA_USER_HOME"]
    ),
    encoding="utf-8",
)
PY
chmod 0644 "$CONF_DST"
chown root:root "$CONF_DST"

systemctl daemon-reload
systemctl reset-failed "$AGENT_UNIT_NAME" >/dev/null 2>&1 || true
systemctl enable --now "$AGENT_UNIT_NAME"
systemctl reset-failed "$UNIT_NAME" >/dev/null 2>&1 || true
# Keep autoconnect enabled, but don't block installation if it can't start now.
systemctl enable "$UNIT_NAME" >/dev/null 2>&1 || true
systemctl start "$UNIT_NAME" >/dev/null 2>&1 || true

systemctl is-active --quiet "$AGENT_UNIT_NAME"

runtime_uid="${PKEXEC_UID:-}"
runtime_user="${SUDO_USER:-}"
if [ -z "$runtime_user" ] && [ -n "$runtime_uid" ]; then
  runtime_user="$(getent passwd "$runtime_uid" | cut -d: -f1 || true)"
fi

if [ -n "$runtime_uid" ] && [ -n "$runtime_user" ]; then
  # Best effort: refresh the user hanauta-service cache right after install.
  runuser -u "$runtime_user" -- env XDG_RUNTIME_DIR="/run/user/$runtime_uid" \
    systemctl --user restart hanauta-service >/dev/null 2>&1 || true
fi

# Warm-up cache: ask the root agent to refresh interfaces now.
if [ -d /run/hanauta-wireguard-agent ]; then
  cat > /run/hanauta-wireguard-agent/request.json <<EOF
{"request_id":"install-refresh","action":"list_interfaces","interface":"","requested_at":$(date +%s)}
EOF
fi

echo "Installed and enabled: $UNIT_NAME, $AGENT_UNIT_NAME"
echo "Status checks:"
systemctl --no-pager --full -n 5 status "$AGENT_UNIT_NAME" || true
systemctl --no-pager --full -n 5 status "$UNIT_NAME" || true
