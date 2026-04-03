#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

PLUGIN_ROOT = Path(__file__).resolve().parent
VPN_POPUP = PLUGIN_ROOT / "vpn_control.py"
SERVICE_KEY = "vpn_control"

DEFAULT_SERVICE = {
    "enabled": True,
    "show_in_notification_center": False,
    "show_in_bar": False,
}


def _save_settings(window) -> None:
    module = sys.modules.get(window.__class__.__module__)
    save_function = (
        getattr(module, "save_settings_state", None) if module is not None else None
    )
    if callable(save_function):
        save_function(window.settings_state)
        return
    callback = getattr(window, "_save_settings", None)
    if callable(callback):
        callback()


def _service_state(window) -> dict[str, object]:
    services = window.settings_state.setdefault("services", {})
    service = services.setdefault(SERVICE_KEY, dict(DEFAULT_SERVICE))
    if not isinstance(service, dict):
        service = dict(DEFAULT_SERVICE)
        services[SERVICE_KEY] = service
    for key, value in DEFAULT_SERVICE.items():
        service.setdefault(key, value)
    return service


def _launch_vpn_popup(window, api: dict[str, object]) -> None:
    status = getattr(window, "vpn_plugin_status", None)
    if not VPN_POPUP.exists():
        if isinstance(status, QLabel):
            status.setText("vpn_control.py not found in plugin folder.")
        return

    entry_command = api.get("entry_command")
    run_bg = api.get("run_bg")
    command: list[str] = []
    if callable(entry_command):
        try:
            command = list(entry_command(VPN_POPUP))
        except Exception:
            command = []
    if not command:
        command = ["python3", str(VPN_POPUP)]

    if callable(run_bg):
        try:
            run_bg(command)
        except Exception:
            pass

    if isinstance(status, QLabel):
        status.setText("WireGuard popup opened.")


def build_vpn_service_section(window, api: dict[str, object]) -> QWidget:
    SettingsRow = api["SettingsRow"]
    SwitchButton = api["SwitchButton"]
    ExpandableServiceSection = api["ExpandableServiceSection"]
    material_icon = api["material_icon"]
    icon_path = str(api.get("plugin_icon_path", "")).strip()

    service = _service_state(window)

    content = QWidget()
    layout = QVBoxLayout(content)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(10)

    display_switch = SwitchButton(bool(service.get("show_in_notification_center", False)))
    display_switch.toggledValue.connect(
        lambda enabled: window._set_service_notification_visibility(SERVICE_KEY, enabled)
    )
    window.service_display_switches[SERVICE_KEY] = display_switch
    layout.addWidget(
        SettingsRow(
            material_icon("widgets"),
            "Show in notification center",
            "Expose WireGuard controls in notification center services.",
            window.icon_font,
            window.ui_font,
            display_switch,
        )
    )

    bar_switch = SwitchButton(bool(service.get("show_in_bar", False)))
    bar_switch.toggledValue.connect(
        lambda enabled: window._set_service_bar_visibility(SERVICE_KEY, enabled)
    )
    layout.addWidget(
        SettingsRow(
            material_icon("shield"),
            "Show on bar",
            "Keep WireGuard quick toggle visible in the top bar.",
            window.icon_font,
            window.ui_font,
            bar_switch,
        )
    )

    open_button = QPushButton("Open WireGuard popup")
    open_button.setObjectName("secondaryButton")
    open_button.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
    open_button.clicked.connect(lambda: _launch_vpn_popup(window, api))
    layout.addWidget(
        SettingsRow(
            material_icon("open_in_new"),
            "Open popup",
            "Launch the VPN control popup window immediately.",
            window.icon_font,
            window.ui_font,
            open_button,
        )
    )

    status_label = QLabel("VPN control plugin ready.")
    status_label.setWordWrap(True)
    status_label.setStyleSheet("color: rgba(246,235,247,0.72);")
    layout.addWidget(status_label)
    window.vpn_plugin_status = status_label

    section = ExpandableServiceSection(
        SERVICE_KEY,
        "VPN Control",
        "WireGuard controls and split-tunneling helpers from plugin runtime.",
        "?",
        window.icon_font,
        window.ui_font,
        content,
        window._service_enabled(SERVICE_KEY),
        lambda enabled: window._set_service_enabled(SERVICE_KEY, enabled),
        icon_path=icon_path,
    )
    window.service_sections[SERVICE_KEY] = section
    return section


def register_hanauta_plugin() -> dict[str, object]:
    return {
        "id": SERVICE_KEY,
        "name": "VPN Control",
        "api_min_version": 1,
        "service_sections": [
            {
                "key": SERVICE_KEY,
                "builder": build_vpn_service_section,
                "supports_show_on_bar": True,
            }
        ],
    }
