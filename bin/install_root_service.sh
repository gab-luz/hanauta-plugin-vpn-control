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

# ----------------------------------------------------------------------
# Resolve the real hanauta user regardless of how this script is invoked.
# pkexec sets PKEXEC_UID, sudo sets SUDO_UID/SUDO_USER.
# ----------------------------------------------------------------------
resolve_user_uid() {
  if [ -n "${PKEXEC_UID:-}" ] && [ "${PKEXEC_UID:-0}" -gt 1000 ] 2>/dev/null; then
    echo "$PKEXEC_UID"
  elif [ -n "${SUDO_UID:-}" ] && [ "${SUDO_UID:-0}" -gt 1000 ] 2>/dev/null; then
    echo "$SUDO_UID"
  elif [ -n "${SUDO_USER:-}" ]; then
    id -u "$SUDO_USER" 2>/dev/null || true
  fi
}

resolve_user_home() {
  local uid_text home dir
  uid_text="$(resolve_user_uid)"
  if [ -n "$uid_text" ]; then
    home="$(getent passwd "$uid_text" 2>/dev/null | cut -d: -f6)"
    if [ -n "$home" ] && [ -d "$home" ]; then
      echo "$home"
      return 0
    fi
  fi
  # Fallback: any home with an existing hanauta install.
  for dir in /home/*; do
    if [ -d "$dir/.config/i3/hanauta" ] || [ -d "$dir/.config/i3/hanauta/src" ]; then
      echo "$dir"
      return 0
    fi
  done
  echo "${HOME:-/root}"
}

# ----------------------------------------------------------------------
# Interface discovery. Never guesses/hardcodes a tunnel name.
# Priority: settings preferred_interface -> first /etc/wireguard conf ->
# already-enabled wg-quick@ instance.
# ----------------------------------------------------------------------
settings_preferred_iface() {
  local home="$1"
  local settings
  [ -n "$home" ] || return 0
  settings="$home/.local/state/hanauta/notification-center/settings.json"
  [ -f "$settings" ] || return 0
  python3 - "$settings" <<'PY'
import json
import sys

try:
    with open(sys.argv[1], encoding="utf-8") as handle:
        payload = json.load(handle)
except Exception:
    raise SystemExit(0)
services = payload.get("services", {}) if isinstance(payload, dict) else {}
vpn = services.get("vpn_control", {}) if isinstance(services, dict) else {}
iface = str(vpn.get("preferred_interface", "")).strip()
if iface:
    print(iface)
PY
}

first_wg_conf() {
  [ -d /etc/wireguard ] || return 0
  local first_conf
  first_conf="$(find /etc/wireguard -maxdepth 1 -type f -name '*.conf' 2>/dev/null | sort | head -n 1 || true)"
  if [ -n "$first_conf" ]; then
    basename "$first_conf" .conf
  fi
}

enabled_wgquick_iface() {
  systemctl list-unit-files 'wg-quick@*.service' --no-legend 2>/dev/null \
    | awk '$2 == "enabled" { sub(/^wg-quick@/, ""); sub(/\.service$/, ""); print; exit }'
}

ensure_resolvconf() {
  if command -v resolvconf >/dev/null 2>&1; then
    return 0
  fi
  echo "[INFO] resolvconf not found; installing runtime dependency..."
  if command -v pacman >/dev/null 2>&1; then
    pacman -Sy --noconfirm openresolv >/dev/null 2>&1 || true
  elif command -v apt-get >/dev/null 2>&1; then
    apt-get update -qq >/dev/null 2>&1 || true
    apt-get install -y openresolv >/dev/null 2>&1 || apt-get install -y resolvconf >/dev/null 2>&1 || true
  elif command -v dnf >/dev/null 2>&1; then
    dnf -y install openresolv >/dev/null 2>&1 || true
  elif command -v zypper >/dev/null 2>&1; then
    zypper --non-interactive install openresolv >/dev/null 2>&1 || true
  fi
  if ! command -v resolvconf >/dev/null 2>&1; then
    echo "[WARN] resolvconf is still unavailable. wg-quick may fail until dependency is installed." >&2
  fi
}

user_home="$(resolve_user_home)"
runtime_uid="$(resolve_user_uid)"
runtime_user="$(getent passwd "$runtime_uid" 2>/dev/null | cut -d: -f1 || true)"

iface="$(settings_preferred_iface "$user_home")"
if [ -z "$iface" ]; then
  iface="$(first_wg_conf)"
fi
if [ -z "$iface" ]; then
  iface="$(enabled_wgquick_iface)"
fi

ensure_resolvconf

install -D -m 0644 "$UNIT_SRC" "$UNIT_DST"
install -D -m 0755 "$AGENT_SCRIPT_SRC" "$AGENT_SCRIPT_DST"
sed "s|@AGENT_SCRIPT@|$AGENT_SCRIPT_DST|g" "$AGENT_UNIT_SRC" > "$AGENT_UNIT_DST"

# Always keep HANAUTA_USER_HOME updated and preserve existing WG_IFACE when present.
python3 - "$CONF_DST" "$iface" "$user_home" <<'PY'
import sys
from pathlib import Path

conf_path = Path(sys.argv[1])
iface = sys.argv[2].strip()
home = sys.argv[3].strip()
data = {}
if conf_path.exists():
    for line in conf_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip()
selected = data.get("WG_IFACE", iface).strip()
if selected and not (Path("/etc/wireguard") / f"{selected}.conf").exists():
    selected = iface
data["WG_IFACE"] = selected
data["HANAUTA_USER_HOME"] = home
conf_path.write_text(
    "WG_IFACE={}\nHANAUTA_USER_HOME={}\n".format(
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
# Ensure the running process always reloads the latest script on plugin updates.
systemctl restart "$AGENT_UNIT_NAME" >/dev/null 2>&1 || true

# If the user already manages the tunnel with the native wg-quick@ unit,
# let systemd own boot autostart and skip the hanauta autoconnect unit.
if [ -n "$iface" ] && systemctl is-enabled --quiet "wg-quick@${iface}.service" 2>/dev/null; then
  echo "[INFO] wg-quick@${iface}.service is already enabled; boot autostart stays with systemd."
  systemctl disable "$UNIT_NAME" >/dev/null 2>&1 || true
else
  systemctl reset-failed "$UNIT_NAME" >/dev/null 2>&1 || true
  systemctl enable "$UNIT_NAME" >/dev/null 2>&1 || true
  systemctl start "$UNIT_NAME" >/dev/null 2>&1 || true
fi

systemctl is-active --quiet "$AGENT_UNIT_NAME"

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

echo "Installed and enabled: $AGENT_UNIT_NAME"
if [ -n "$iface" ]; then
  echo "WireGuard interface: $iface"
else
  echo "WireGuard interface: (none detected; pick one from the Hanauta VPN popup)"
fi
echo "Hanauta user home: $user_home"
echo "Status checks:"
systemctl --no-pager --full -n 5 status "$AGENT_UNIT_NAME" || true
systemctl --no-pager --full -n 5 status "$UNIT_NAME" || true
