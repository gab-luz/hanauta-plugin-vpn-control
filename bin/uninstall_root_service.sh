#!/usr/bin/env bash
set -euo pipefail

UNIT_NAME="hanauta-wireguard-autoconnect.service"
AGENT_UNIT_NAME="hanauta-wireguard-agent.service"
UNIT_DST="/etc/systemd/system/$UNIT_NAME"
AGENT_UNIT_DST="/etc/systemd/system/$AGENT_UNIT_NAME"
AGENT_DIR="/usr/local/lib/hanauta-plugin-vpn-control"

if command -v systemctl >/dev/null 2>&1; then
  systemctl disable --now "$UNIT_NAME" >/dev/null 2>&1 || true
  systemctl disable --now "$AGENT_UNIT_NAME" >/dev/null 2>&1 || true
  systemctl reset-failed "$UNIT_NAME" >/dev/null 2>&1 || true
  systemctl reset-failed "$AGENT_UNIT_NAME" >/dev/null 2>&1 || true
  rm -f "$UNIT_DST" || true
  rm -f "$AGENT_UNIT_DST" || true
  rm -rf "$AGENT_DIR" || true
  systemctl daemon-reload >/dev/null 2>&1 || true
else
  rm -f "$UNIT_DST" || true
  rm -f "$AGENT_UNIT_DST" || true
  rm -rf "$AGENT_DIR" || true
fi

echo "Removed: $UNIT_NAME and $AGENT_UNIT_NAME"
