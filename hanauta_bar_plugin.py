#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from PyQt6.QtCore import QSize
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QPushButton

SETTINGS_FILE = (
    Path.home()
    / ".local"
    / "state"
    / "hanauta"
    / "notification-center"
    / "settings.json"
)
_LAST_THEME_CHOICE = "dark"


def _theme_choice() -> str:
    global _LAST_THEME_CHOICE
    try:
        payload = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return _LAST_THEME_CHOICE
    appearance = payload.get("appearance", {}) if isinstance(payload, dict) else {}
    appearance = appearance if isinstance(appearance, dict) else {}
    if bool(appearance.get("use_matugen_palette", False)):
        _LAST_THEME_CHOICE = "wallpaper_aware"
        return _LAST_THEME_CHOICE
    choice = str(appearance.get("theme_choice", "")).strip().lower()
    if choice == "wallpaper-aware":
        _LAST_THEME_CHOICE = "wallpaper_aware"
        return _LAST_THEME_CHOICE
    if choice:
        _LAST_THEME_CHOICE = choice
        return _LAST_THEME_CHOICE
    fallback = str(appearance.get("theme_mode", "dark")).strip().lower()
    _LAST_THEME_CHOICE = fallback if fallback else _LAST_THEME_CHOICE
    return _LAST_THEME_CHOICE


def _pick_plugin_icon(plugin_dir: Path) -> Path | None:
    theme = _theme_choice()
    use_color = theme in {"dark", "light", "custom"}
    candidates = (
        [
            plugin_dir / "icon_color.svg",
            plugin_dir / "assets" / "icon_color.svg",
            plugin_dir / "icon.svg",
            plugin_dir / "assets" / "icon.svg",
        ]
        if use_color
        else [
            plugin_dir / "icon.svg",
            plugin_dir / "assets" / "icon.svg",
            plugin_dir / "icon_color.svg",
            plugin_dir / "assets" / "icon_color.svg",
        ]
    )
    for path in candidates:
        if path.exists():
            return path
    return None


def _apply_vpn_button_icon(bar, plugin_dir: Path) -> None:
    button = getattr(bar, "vpn_icon", None)
    if not isinstance(button, QPushButton):
        return
    icon_path = _pick_plugin_icon(plugin_dir)
    if icon_path is None:
        return
    icon = QIcon(str(icon_path))
    if icon.isNull():
        return
    button.setIcon(icon)
    button.setIconSize(QSize(16, 16))
    button.setText("")
    button.setProperty("vpnPluginIconPath", str(icon_path))


def register_hanauta_bar_plugin(bar, api: dict[str, object]) -> None:
    plugin_dir = Path(str(api.get("plugin_dir", ""))).expanduser()
    register_hook = api.get("register_hook")
    if not callable(register_hook):
        return

    def _refresh() -> None:
        _apply_vpn_button_icon(bar, plugin_dir)

    register_hook("icons", _refresh)
    register_hook("settings_reloaded", _refresh)
    register_hook("poll", _refresh)
    _refresh()
