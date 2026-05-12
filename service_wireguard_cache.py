#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

SETTINGS_FILE = (
    Path.home()
    / ".local"
    / "state"
    / "hanauta"
    / "notification-center"
    / "settings.json"
)
WG_CONF_DIR = Path("/etc/wireguard")


def _service_state_dir() -> Path:
    env_dir = os.environ.get("HANAUTA_SERVICE_STATE_DIR", "").strip()
    if env_dir:
        return Path(env_dir)
    return Path.home() / ".local" / "state" / "hanauta" / "service"


def _cache_path() -> Path:
    return _service_state_dir() / "plugins" / "vpn_control_wireguard.json"


def _selected_from_settings() -> str:
    try:
        payload = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return ""
    services = payload.get("services", {}) if isinstance(payload, dict) else {}
    if not isinstance(services, dict):
        return ""
    current = services.get("vpn_control", {})
    if not isinstance(current, dict):
        return ""
    return str(current.get("preferred_interface", "")).strip()


def _list_wireguard_configs() -> list[str]:
    if not WG_CONF_DIR.exists() or not WG_CONF_DIR.is_dir():
        return []
    names: list[str] = []
    for path in sorted(WG_CONF_DIR.glob("*.conf")):
        name = path.stem.strip()
        if name:
            names.append(name)
    return names


def _wireguard_status(iface: str) -> str:
    if not iface:
        return "off"
    try:
        result = subprocess.run(
            ["ip", "link", "show", iface],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
    except Exception:
        return "off"
    if result.returncode != 0:
        return "off"
    text = result.stdout
    if " state UP " in text:
        return "on"
    if "<" in text and ">" in text:
        try:
            flags = text.split("<", 1)[1].split(">", 1)[0]
            parts = [part.strip().upper() for part in flags.split(",") if part.strip()]
            if "UP" in parts:
                return "on"
        except Exception:
            pass
    return "off"


def main() -> int:
    interfaces = _list_wireguard_configs()
    preferred = _selected_from_settings()
    selected = preferred if preferred in interfaces else (interfaces[0] if interfaces else "")
    payload = {
        "wireguard": _wireguard_status(selected),
        "wg_selected": selected,
        "interfaces": interfaces,
    }
    cache_path = _cache_path()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(payload, ensure_ascii=True), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
