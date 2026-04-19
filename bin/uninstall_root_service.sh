#!/usr/bin/env bash
set -euo pipefail

UNIT_NAME="hanauta-wireguard-autoconnect.service"
UNIT_DST="/etc/systemd/system/$UNIT_NAME"

if command -v systemctl >/dev/null 2>&1; then
  systemctl disable --now "$UNIT_NAME" >/dev/null 2>&1 || true
  systemctl reset-failed "$UNIT_NAME" >/dev/null 2>&1 || true
  rm -f "$UNIT_DST" || true
  systemctl daemon-reload >/dev/null 2>&1 || true
else
  rm -f "$UNIT_DST" || true
fi

echo "Removed: $UNIT_NAME"
