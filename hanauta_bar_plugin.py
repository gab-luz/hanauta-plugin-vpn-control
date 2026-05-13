#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from types import MethodType

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QPushButton

SERVICE_KEY = "vpn_control"
SERVICE_STATE_DIR = Path.home() / ".local" / "state" / "hanauta" / "service"
VPN_CACHE_FILE = SERVICE_STATE_DIR / "plugins" / "vpn_control_wireguard.json"

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


def _pick_plugin_state_icons(
    plugin_dir: Path,
) -> tuple[Path | None, Path | None, Path | None]:
    # For dark/light themes, use state-aware outline VPN icons.
    theme = _theme_choice()
    if theme in {"dark", "light", "custom"}:
        active_candidates = [
            plugin_dir / "assets" / "vpn-key-outline.svg",
            plugin_dir / "assets" / "vpn-key-out.svg",
            plugin_dir / "vpn-key-outline.svg",
            plugin_dir / "vpn-key-out.svg",
            plugin_dir / "assets" / "icon.svg",
            plugin_dir / "icon.svg",
        ]
        inactive_candidates = [
            plugin_dir / "assets" / "vpn-key-off-outline.svg",
            plugin_dir / "vpn-key-off-outline.svg",
            plugin_dir / "assets" / "icon.svg",
            plugin_dir / "icon.svg",
        ]
        alert_candidates = [
            plugin_dir / "assets" / "vpn-key-alert-outline.svg",
            plugin_dir / "vpn-key-alert-outline.svg",
            plugin_dir / "assets" / "vpn-key-off-outline.svg",
            plugin_dir / "vpn-key-off-outline.svg",
            plugin_dir / "assets" / "icon.svg",
            plugin_dir / "icon.svg",
        ]

        def first_existing(candidates: list[Path]) -> Path | None:
            for path in candidates:
                if path.exists():
                    return path
            return None

        active = first_existing(active_candidates)
        inactive = first_existing(inactive_candidates)
        alert = first_existing(alert_candidates)
        return active, inactive, alert

    # Wallpaper-aware and other modes: keep a single plugin icon.
    chosen = _pick_plugin_icon(plugin_dir)
    return chosen, chosen, chosen


def _apply_vpn_button_icon(bar, plugin_dir: Path) -> None:
    button = getattr(bar, "vpn_icon", None)
    if not isinstance(button, QPushButton):
        return
    active_icon, inactive_icon, alert_icon = _pick_plugin_state_icons(plugin_dir)
    if active_icon is None or inactive_icon is None:
        return
    active_str = str(active_icon)
    inactive_str = str(inactive_icon)
    alert_str = str(alert_icon) if alert_icon is not None else inactive_str
    if str(button.property("pluginIconPathActive") or "") != active_str:
        button.setProperty("pluginIconPathActive", active_str)
    if str(button.property("pluginIconPathInactive") or "") != inactive_str:
        button.setProperty("pluginIconPathInactive", inactive_str)
    if str(button.property("pluginIconPathAlert") or "") != alert_str:
        button.setProperty("pluginIconPathAlert", alert_str)


def _load_vpn_state() -> dict[str, object]:
    try:
        payload = json.loads(VPN_CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _apply_vpn_runtime_state(bar) -> None:
    button = getattr(bar, "vpn_icon", None)
    if not isinstance(button, QPushButton):
        return
    payload = _load_vpn_state()
    state = str(payload.get("wireguard", "")).strip().lower()
    selected = str(payload.get("wg_selected", "")).strip()
    has_ifaces = bool(payload.get("interfaces", []))
    active = state == "on"
    alert = state not in {"on", "off"} or not has_ifaces or not selected
    button.setProperty("active", active)
    button.setProperty("alert", alert)
    button.setToolTip(f"WireGuard: {selected or 'No config selected'}")
    refresh = getattr(bar, "_set_vpn_button_icon", None)
    if callable(refresh):
        try:
            refresh(active, alert=alert)
        except Exception:
            pass
    style = getattr(bar, "style", None)
    if callable(style):
        try:
            bar.style().unpolish(button)
            bar.style().polish(button)
        except Exception:
            pass


def _install_vpn_popup_sync_override(bar) -> None:
    # Host bars may sync vpn_icon.active from popup-open state, which clobbers
    # real WireGuard on/off state. Override VPN-only sync to preserve active.
    original_sync_vpn = getattr(bar, "_sync_vpn_button", None)
    if not callable(original_sync_vpn):
        return
    if bool(getattr(bar, "_vpn_sync_override_installed", False)):
        return

    def _sync_vpn_button(self) -> None:
        original_sync_vpn()
        _apply_vpn_runtime_state(self)

    setattr(bar, "_sync_vpn_button", MethodType(_sync_vpn_button, bar))
    setattr(bar, "_vpn_sync_override_installed", True)


def _install_vpn_popup_launcher(bar, plugin_dir: Path) -> None:
    script_path = plugin_dir / "vpn_control.py"
    if not script_path.exists():
        return
    setattr(bar, "_vpn_control_script", script_path)
    toggle_singleton = getattr(bar, "_toggle_singleton_process", None)
    python_bin = getattr(bar, "_python_bin", None)
    if not callable(toggle_singleton) or not callable(python_bin):
        return
    if bool(getattr(bar, "_vpn_launcher_override_installed", False)):
        return

    def _toggle_vpn_popup(self) -> None:
        vpn_script = getattr(self, "_vpn_control_script", script_path)
        if vpn_script is None or not Path(vpn_script).exists():
            self.vpn_icon.setChecked(False)
            return
        self._toggle_singleton_process(
            "_vpn_popup_process",
            Path(vpn_script),
            python_bin=self._python_bin(),
        )
        QTimer.singleShot(150, self._sync_vpn_button)

    setattr(bar, "_toggle_vpn_popup", MethodType(_toggle_vpn_popup, bar))
    try:
        bar.vpn_icon.clicked.disconnect()
    except Exception:
        pass
    bar.vpn_icon.clicked.connect(bar._toggle_vpn_popup)
    setattr(bar, "_vpn_launcher_override_installed", True)


def register_hanauta_bar_plugin(bar, api: dict[str, object]) -> None:
    plugin_dir = Path(str(api.get("plugin_dir", ""))).expanduser()
    register_hook = api.get("register_hook")
    if not callable(register_hook):
        return

    def _refresh() -> None:
        _apply_vpn_button_icon(bar, plugin_dir)
        _apply_vpn_runtime_state(bar)

    register_hook("icons", _refresh)
    register_hook("settings_reloaded", _refresh)
    register_hook("poll", _apply_vpn_runtime_state)
    _install_vpn_popup_launcher(bar, plugin_dir)
    _install_vpn_popup_sync_override(bar)
    _refresh()
