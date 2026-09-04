#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Compact PyQt6 WireGuard control popup.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import time
import uuid
import traceback
from pathlib import Path

from PyQt6.QtCore import QThread, Qt, QTimer, QSize, QStringListModel, pyqtSignal
from PyQt6.QtGui import QColor, QCursor, QFont, QFontDatabase, QIcon, QPainter, QPalette, QPixmap
try:
    from PyQt6.QtSvg import QSvgRenderer
except ModuleNotFoundError:
    QSvgRenderer = None
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


try:
    from pyqt.shared.runtime import fonts_root, scripts_root, source_root
    from pyqt.shared.theme import load_theme_palette, palette_mtime, rgba
    from pyqt.shared.button_helpers import create_close_button
except ModuleNotFoundError:
    fallback_src = Path.home() / ".config" / "i3" / "hanauta" / "src"
    if fallback_src.exists() and str(fallback_src) not in sys.path:
        sys.path.insert(0, str(fallback_src))
    from pyqt.shared.runtime import fonts_root, scripts_root, source_root
    from pyqt.shared.theme import load_theme_palette, palette_mtime, rgba
    from pyqt.shared.button_helpers import create_close_button

# Localization
try:
    from i18n import _, N_, init_language, get_supported_languages
except ModuleNotFoundError:
    # Fallback if i18n module not available
    def _(message: str) -> str:
        return message
    def N_(message: str) -> str:
        return message
    def init_language(config_lang: str | None = None) -> str:
        return "en_US"
    def get_supported_languages() -> dict[str, str]:
        return {
            "en_US": "English (US)",
            "pt_BR": "Português (Brasil)",
            "ru_RU": "Русский",
            "es_AR": "Español (Argentina)",
        }

APP_DIR = source_root()
if str(APP_DIR) not in sys.path:
    sys.path.append(str(APP_DIR))

SCRIPTS_DIR = scripts_root()
FONTS_DIR = fonts_root()
STATE_DIR = Path.home() / ".local" / "state" / "hanauta" / "notification-center"
SETTINGS_FILE = STATE_DIR / "settings.json"
SERVICE_STATE_DIR = Path.home() / ".local" / "state" / "hanauta" / "service"
VPN_CACHE_FILE = SERVICE_STATE_DIR / "plugins" / "vpn_control_wireguard.json"
VPN_LOG_FILE = STATE_DIR / "vpn_control.log"
WG_AGENT_RUN_DIR = Path("/run/hanauta-wireguard-agent")
WG_AGENT_REQUEST_FILE = WG_AGENT_RUN_DIR / "request.json"
WG_AGENT_RESPONSE_FILE = WG_AGENT_RUN_DIR / "response.json"
ICON_ASSETS_DIR = APP_DIR / "assets" / "icons"
PLUGIN_ROOT = Path(__file__).resolve().parent
PLUGIN_ASSETS_DIR = PLUGIN_ROOT / "assets"
VPN_ICON_HEADER = PLUGIN_ASSETS_DIR / "wireguard_brand.svg"
VPN_ICON_ROW = PLUGIN_ASSETS_DIR / "vpn_key.svg"
VPN_ICON_STATE_ACTIVE = PLUGIN_ASSETS_DIR / "vpn_shield_check.svg"
VPN_ICON_STATE_INACTIVE = PLUGIN_ASSETS_DIR / "vpn_lock.svg"
VPN_ICON_STATE_PENDING = PLUGIN_ASSETS_DIR / "vpn_world.svg"
VPN_ICON_ACTION_REFRESH = PLUGIN_ASSETS_DIR / "vpn_world.svg"
VPN_ICON_ACTION_ADD = PLUGIN_ASSETS_DIR / "vpn_key.svg"
VPN_ICON_ACTION_REMOVE = PLUGIN_ASSETS_DIR / "vpn_lock.svg"
VPN_ICON_ACTION_CLEAR = PLUGIN_ASSETS_DIR / "vpn_shield_lock.svg"
DESKTOP_DIRS = [
    Path.home() / ".local" / "share" / "applications",
    Path("/usr/local/share/applications"),
    Path("/usr/share/applications"),
]

MATERIAL_ICONS = {
    "close": "\ue5cd",
    "lock": "\ue897",
    "lock_open": "\ue898",
    "refresh": "\ue5d5",
    "shield": "\ue9e0",
    "tune": "\ue429",
    "rocket": "\ue9d0",
    "add": "\ue145",
    "delete": "\ue872",
    "delete_sweep": "\ue16c",
}


def service_enabled() -> bool:
    try:
        raw = SETTINGS_FILE.read_text(encoding="utf-8")
        payload = json.loads(raw)
    except Exception:
        return True
    services = payload.get("services", {})
    if not isinstance(services, dict):
        return True
    current = services.get("vpn_control", {})
    if not isinstance(current, dict):
        return True
    return bool(current.get("enabled", True))


def load_vpn_service_settings() -> dict[str, object]:
    try:
        raw = SETTINGS_FILE.read_text(encoding="utf-8")
        payload = json.loads(raw)
    except Exception:
        return {}
    services = payload.get("services", {})
    if not isinstance(services, dict):
        return {}
    current = services.get("vpn_control", {})
    return current if isinstance(current, dict) else {}


def save_vpn_service_setting(key: str, value: object) -> None:
    try:
        raw = SETTINGS_FILE.read_text(encoding="utf-8")
        payload = json.loads(raw)
    except Exception:
        payload = {}
    services = payload.get("services", {})
    if not isinstance(services, dict):
        services = {}
    current = services.get("vpn_control", {})
    if not isinstance(current, dict):
        current = {}
    current[key] = value
    services["vpn_control"] = current
    payload["services"] = services
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def run_cmd(cmd: list[str], timeout: float = 3.0) -> str:
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return result.stdout.strip()
    except Exception:
        return ""


def run_script(script_name: str, *args: str) -> str:
    script_path = SCRIPTS_DIR / script_name
    if not script_path.exists():
        return ""
    return run_cmd([str(script_path), *args])


def run_script_bg(script_name: str, *args: str) -> None:
    script_path = SCRIPTS_DIR / script_name
    if not script_path.exists():
        return
    try:
        subprocess.Popen(
            [str(script_path), *args],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


def load_wireguard_cache() -> dict[str, object]:
    try:
        payload = json.loads(VPN_CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def save_wireguard_cache(payload: dict[str, object]) -> None:
    try:
        VPN_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        VPN_CACHE_FILE.write_text(json.dumps(payload, ensure_ascii=True), encoding="utf-8")
    except Exception:
        pass


def wireguard_service_request(
    action: str, *, interface: str = "", timeout: float = 4.0
) -> dict[str, object]:
    if not WG_AGENT_RUN_DIR.exists():
        return {"ok": False, "message": "Hanauta WireGuard root agent is not running."}
    request_id = str(uuid.uuid4())
    payload = {
        "request_id": request_id,
        "action": action,
        "interface": interface,
        "requested_at": time.time(),
    }
    try:
        WG_AGENT_REQUEST_FILE.write_text(
            json.dumps(payload, ensure_ascii=True), encoding="utf-8"
        )
    except Exception as exc:
        return {"ok": False, "message": f"Failed to talk to root agent: {exc}"}

    deadline = time.time() + max(0.5, timeout)
    while time.time() < deadline:
        try:
            raw = WG_AGENT_RESPONSE_FILE.read_text(encoding="utf-8")
            response = json.loads(raw)
        except Exception:
            time.sleep(0.1)
            continue
        if not isinstance(response, dict):
            time.sleep(0.1)
            continue
        if str(response.get("request_id", "")).strip() != request_id:
            time.sleep(0.1)
            continue
        return response
    return {"ok": False, "message": "Timed out waiting for Hanauta WireGuard root agent."}


def append_log(message: str) -> None:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        with VPN_LOG_FILE.open("a", encoding="utf-8") as handle:
            handle.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")
    except Exception:
        pass


def material_icon(name: str) -> str:
    return MATERIAL_ICONS.get(name, "?")


def themed_icon(path: Path, fallback_theme_name: str = "") -> QIcon:
    if path.exists():
        return QIcon(str(path))
    if fallback_theme_name:
        icon = QIcon.fromTheme(fallback_theme_name)
        if not icon.isNull():
            return icon
    return QIcon()


def tinted_svg_pixmap(path: Path, color: QColor, size: int = 18) -> QPixmap | None:
    if not path.exists():
        return None
    if QSvgRenderer is None:
        return None
    renderer = QSvgRenderer()
    if not renderer.load(str(path)) or not renderer.isValid():
        return None
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    renderer.render(painter)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(pixmap.rect(), color)
    painter.end()
    return pixmap if not pixmap.isNull() else None


def normalize_split_tunnel_apps(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    for item in value:
        if isinstance(item, str):
            s = item.strip()
            if s:
                normalized.append(s)
        elif isinstance(item, dict):
            target = str(item.get("target", "")).strip()
            if target:
                normalized.append(target)
    return normalized


def normalize_split_tunnel_domains(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    for item in value:
        if isinstance(item, str):
            s = item.strip()
            if s:
                normalized.append(s)
        elif isinstance(item, dict):
            domain = str(item.get("domain", item.get("target", ""))).strip()
            if domain:
                normalized.append(domain)
    return normalized


def load_split_tunnel_config() -> dict[str, object]:
    settings = load_vpn_service_settings()
    split = settings.get("split_tunnel", {})
    if not isinstance(split, dict):
        split = {}
    return {
        "enabled": bool(split.get("enabled", False)),
        "mode": str(split.get("mode", "inclusive")).strip().lower(),
        "kill_switch": bool(split.get("kill_switch", False)),
        "apps_vpn": normalize_split_tunnel_apps(split.get("apps", {}).get("vpn", [])),
        "apps_direct": normalize_split_tunnel_apps(split.get("apps", {}).get("direct", [])),
        "domains_vpn": normalize_split_tunnel_domains(split.get("domains", {}).get("vpn", [])),
        "domains_direct": normalize_split_tunnel_domains(split.get("domains", {}).get("direct", [])),
        "resolve_interval_secs": int(split.get("domains", {}).get("resolve_interval_secs", 300)),
        "default_route_vpn": bool(split.get("default_route_vpn", True)),
    }


def save_split_tunnel_config(config: dict[str, object]) -> None:
    settings = load_vpn_service_settings()
    split = settings.get("split_tunnel", {})
    if not isinstance(split, dict):
        split = {}
    split.update(config)
    settings["split_tunnel"] = split
    save_vpn_service_setting("split_tunnel", split)


def get_split_tunnel_mode_label(mode: str) -> str:
    return "Inclusive (only listed apps use VPN)" if mode == "inclusive" else "Exclusive (listed apps bypass VPN)"


def parse_desktop_entry(path: Path) -> dict[str, str] | None:
    try:
        raw = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None

    entry: dict[str, str] = {}
    in_desktop_entry = False
    for raw_line in raw.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("["):
            in_desktop_entry = line == "[Desktop Entry]"
            continue
        if not in_desktop_entry or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key not in entry:
            entry[key] = value.strip()

    if entry.get("Type") != "Application":
        return None
    if entry.get("NoDisplay", "").lower() == "true" or entry.get("Hidden", "").lower() == "true":
        return None
    if entry.get("X-HanautaSplitTunnel", "").lower() == "true":
        return None

    name = entry.get("Name", "").strip()
    if not name:
        return None
    return {
        "name": name,
        "desktop_id": path.name,
        "comment": entry.get("Comment", "").strip(),
        "icon_name": entry.get("Icon", "").strip(),
        "source_path": str(path),
    }


def scan_desktop_apps() -> list[dict[str, str]]:
    apps: list[dict[str, str]] = []
    seen: set[str] = set()
    for directory in DESKTOP_DIRS:
        if not directory.exists():
            continue
        for path in sorted(directory.rglob("*.desktop")):
            entry = parse_desktop_entry(path)
            if entry is None:
                continue
            desktop_id = entry["desktop_id"].lower()
            if desktop_id in seen:
                continue
            seen.add(desktop_id)
            apps.append(entry)
    apps.sort(key=lambda item: item["name"].lower())
    return apps


def scan_flatpak_apps() -> list[dict[str, str]]:
    if not shutil.which("flatpak"):
        return []
    try:
        result = subprocess.run(
            ["flatpak", "list", "--app", "--columns=application,name"],
            capture_output=True,
            text=True,
            timeout=5.0,
            check=False,
        )
    except Exception:
        return []
    if result.returncode != 0:
        return []
    apps: list[dict[str, str]] = []
    for line in result.stdout.splitlines():
        parts = [part.strip() for part in line.split("\t") if part.strip()]
        if not parts:
            continue
        app_id = parts[0]
        name = parts[1] if len(parts) > 1 else app_id
        apps.append({"app_id": app_id, "name": name})
    apps.sort(key=lambda item: item["name"].lower())
    return apps


def slugify_label(value: str) -> str:
    slug = "".join(ch.lower() if ch.isalnum() else "-" for ch in value.strip())
    slug = "-".join(part for part in slug.split("-") if part)
    return slug or "app"


class AppSelectionDialog(QDialog):
    def __init__(
        self,
        theme,
        apps: list[dict[str, str]],
        *,
        title_text: str = "Add apps outside VPN",
        subtitle_text: str = "Search installed apps, use autocomplete, and select multiple entries at once.",
        placeholder_text: str = "Type an app name or desktop id",
        add_button_text: str = "Add selected apps",
        primary_label_key: str = "name",
        secondary_parts: tuple[str, ...] = ("comment", "desktop_id"),
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.theme = theme
        self.apps = apps
        self.title_text = title_text
        self.subtitle_text = subtitle_text
        self.placeholder_text = placeholder_text
        self.add_button_text = add_button_text
        self.primary_label_key = primary_label_key
        self.secondary_parts = secondary_parts
        self._label_to_items: dict[str, list[QListWidgetItem]] = {}
        self._completer_model = QStringListModel(self)
        self._setup_window()
        self._build_ui()
        self._populate_apps()
        self._apply_styles()

    def _setup_window(self) -> None:
        self.setWindowTitle(self.title_text)
        self.setModal(True)
        self.resize(520, 440)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        title = QLabel(self.title_text)
        title.setObjectName("dialogTitle")
        layout.addWidget(title)

        subtitle = QLabel(self.subtitle_text)
        subtitle.setObjectName("dialogSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        self.search_input = QLineEdit()
        self.search_input.setObjectName("searchInput")
        self.search_input.setPlaceholderText(self.placeholder_text)
        self.search_input.textChanged.connect(self._filter_items)
        layout.addWidget(self.search_input)

        self.completer = QCompleter(self._completer_model, self)
        self.completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self.completer.activated.connect(self._select_from_completion)
        self.search_input.setCompleter(self.completer)

        self.app_list = QListWidget()
        self.app_list.setObjectName("appList")
        self.app_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        layout.addWidget(self.app_list, 1)

        self.selection_label = QLabel("0 apps selected")
        self.selection_label.setObjectName("dialogSubtitle")
        layout.addWidget(self.selection_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(self.add_button_text)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.button_box = buttons

        self.app_list.itemSelectionChanged.connect(self._update_selection_label)

    def _populate_apps(self) -> None:
        labels: list[str] = []
        self.app_list.clear()
        self._label_to_items.clear()
        for app in self.apps:
            label = str(app.get(self.primary_label_key, "")).strip()
            detail_parts = [str(app.get(key, "")).strip() for key in self.secondary_parts]
            detail = " · ".join([part for part in detail_parts if part])
            item = QListWidgetItem(f"{label}\n{detail}")
            item.setData(Qt.ItemDataRole.UserRole, app)
            item.setData(Qt.ItemDataRole.UserRole + 1, label)
            item.setData(Qt.ItemDataRole.UserRole + 2, detail)
            self.app_list.addItem(item)
            self._label_to_items.setdefault(label, []).append(item)
            labels.append(label)
        self._completer_model.setStringList(sorted(set(labels), key=str.lower))
        self._update_selection_label()

    def _filter_items(self, text: str) -> None:
        query = text.strip().lower()
        for index in range(self.app_list.count()):
            item = self.app_list.item(index)
            haystack = " ".join(
                [
                    str(item.data(Qt.ItemDataRole.UserRole + 1) or ""),
                    str(item.data(Qt.ItemDataRole.UserRole + 2) or ""),
                ]
            ).lower()
            item.setHidden(bool(query) and query not in haystack)

    def _select_from_completion(self, label: str) -> None:
        self.search_input.setText(label)
        for item in self._label_to_items.get(label, []):
            item.setHidden(False)
            item.setSelected(True)
            self.app_list.scrollToItem(item)
        self._update_selection_label()

    def _update_selection_label(self) -> None:
        count = len(self.selected_apps())
        self.selection_label.setText(f"{count} app{'s' if count != 1 else ''} selected")

    def selected_apps(self) -> list[dict[str, str]]:
        selected: list[dict[str, str]] = []
        for item in self.app_list.selectedItems():
            payload = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(payload, dict):
                selected.append(payload)
        return selected

    def _apply_styles(self) -> None:
        theme = self.theme
        self.setStyleSheet(
            f"""
            QDialog {{
                background: {rgba(theme.surface_container_high, 0.96)};
                color: {theme.text};
            }}
            QLabel#dialogTitle {{
                color: {theme.text};
                font-size: 15px;
                font-weight: 700;
            }}
            QLabel#dialogSubtitle {{
                color: {theme.text_muted};
                font-size: 11px;
            }}
            QLineEdit#searchInput {{
                background: {rgba(theme.surface_container_high, 0.92)};
                color: {theme.text};
                border: 1px solid {theme.chip_border};
                border-radius: 14px;
                padding: 10px 12px;
            }}
            QListWidget#appList {{
                background: {rgba(theme.surface_container_high, 0.90)};
                color: {theme.text};
                border: 1px solid {theme.chip_border};
                border-radius: 18px;
                outline: none;
                padding: 6px;
            }}
            QListWidget#appList::item {{
                padding: 10px 12px;
                margin: 2px 0;
                border-radius: 12px;
            }}
            QListWidget#appList::item:selected {{
                background: {theme.hover_bg};
                color: {theme.text};
            }}
            QAbstractItemView {{
                background: {rgba(theme.surface_container_high, 0.98)};
                color: {theme.text};
                border: 1px solid {theme.chip_border};
                selection-background-color: {theme.hover_bg};
                selection-color: {theme.text};
            }}
            QDialogButtonBox QPushButton {{
                background: {theme.chip_bg};
                color: {theme.text};
                border: 1px solid {theme.chip_border};
                border-radius: 14px;
                min-height: 38px;
                padding: 0 16px;
            }}
            QDialogButtonBox QPushButton:hover {{
                background: {theme.hover_bg};
            }}
            """
        )


class DomainInputDialog(QDialog):
    def __init__(self, theme, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.theme = theme
        self._domain = ""
        self.setWindowTitle(title)
        self.setModal(True)
        self.resize(480, 180)
        self._build_ui()
        self._apply_styles()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        title_label = QLabel("Enter domain or IP address")
        title_label.setObjectName("dialogTitle")
        layout.addWidget(title_label)

        subtitle = QLabel("Examples: example.com, 10.0.0.0/8, 192.168.1.0/24")
        subtitle.setObjectName("dialogSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        self.domain_input = QLineEdit()
        self.domain_input.setObjectName("searchInput")
        self.domain_input.setPlaceholderText("example.com or 10.0.0.0/8")
        layout.addWidget(self.domain_input)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Add")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_domain(self) -> str:
        return self._domain

    def accept(self) -> None:
        self._domain = self.domain_input.text().strip()
        super().accept()

    def _apply_styles(self) -> None:
        theme = self.theme
        self.setStyleSheet(
            f"""
            QDialog {{
                background: {rgba(theme.surface_container_high, 0.96)};
                color: {theme.text};
            }}
            QLabel#dialogTitle {{
                color: {theme.text};
                font-size: 15px;
                font-weight: 700;
            }}
            QLabel#dialogSubtitle {{
                color: {theme.text_muted};
                font-size: 11px;
            }}
            QLineEdit#searchInput {{
                background: {rgba(theme.surface_container_high, 0.92)};
                color: {theme.text};
                border: 1px solid {theme.chip_border};
                border-radius: 14px;
                padding: 10px 12px;
            }}
            QDialogButtonBox QPushButton {{
                background: {theme.chip_bg};
                color: {theme.text};
                border: 1px solid {theme.chip_border};
                border-radius: 14px;
                min-height: 38px;
                padding: 0 16px;
            }}
            QDialogButtonBox QPushButton:hover {{
                background: {theme.hover_bg};
            }}
            """
        )


def load_app_fonts() -> dict[str, str]:
    loaded: dict[str, str] = {}
    font_map = {
        "material_icons": FONTS_DIR / "MaterialIcons-Regular.ttf",
        "material_icons_outlined": FONTS_DIR / "MaterialIconsOutlined-Regular.otf",
        "material_symbols_outlined": FONTS_DIR / "MaterialSymbolsOutlined.ttf",
        "material_symbols_rounded": FONTS_DIR / "MaterialSymbolsRounded.ttf",
    }
    for key, path in font_map.items():
        if not path.exists():
            continue
        font_id = QFontDatabase.addApplicationFont(str(path))
        if font_id < 0:
            continue
        families = QFontDatabase.applicationFontFamilies(font_id)
        if families:
            loaded[key] = families[0]
    return loaded


def detect_font(*families: str) -> str:
    for family in families:
        if family and QFont(family).exactMatch():
            return family
    return "Sans Serif"


class VpnToggleWorker(QThread):
    completed = pyqtSignal(bool, str)

    def __init__(self, interface: str) -> None:
        super().__init__()
        self.interface = interface

    def run(self) -> None:
        response = wireguard_service_request("toggle", interface=self.interface, timeout=70.0)
        ok = bool(response.get("ok", False))
        message = str(response.get("message", "")).strip()
        if not message:
            message = "WireGuard updated." if ok else "WireGuard command failed."
        self.completed.emit(ok, message)


class VpnControlPopup(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.loaded_fonts = load_app_fonts()
        self.material_font = detect_font(
            self.loaded_fonts.get("material_icons", ""),
            self.loaded_fonts.get("material_icons_outlined", ""),
            self.loaded_fonts.get("material_symbols_outlined", ""),
            self.loaded_fonts.get("material_symbols_rounded", ""),
            "Material Icons",
            "Material Icons Outlined",
            "Material Symbols Outlined",
            "Material Symbols Rounded",
        )
        self.theme = load_theme_palette()
        self._theme_mtime = palette_mtime()
        self._building_combo = False
        self._building_switch = False
        self._toggle_worker: VpnToggleWorker | None = None
        self._pending_quit_after_toggle = False
        self._desktop_apps_cache: list[dict[str, str]] | None = None
        self._flatpak_apps_cache: list[dict[str, str]] | None = None
        self._privileged_probe_attempted = False
        self._last_privileged_probe_at = 0.0
        self._header_icon_label: QLabel | None = None
        self._row_icon_label: QLabel | None = None
        self._setup_window()
        self._build_ui()
        self._apply_styles()
        self.refresh_state()
        self.footer_label.setText(f"Plugin source: {PLUGIN_ROOT}")

        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self.refresh_state)
        self.poll_timer.start(5000)

        self.theme_timer = QTimer(self)
        self.theme_timer.timeout.connect(self._reload_theme_if_needed)
        self.theme_timer.start(3000)

    def _setup_window(self) -> None:
        self.setWindowTitle("WireGuard")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.resize(420, 560)

        screen = QApplication.primaryScreen()
        geo = screen.availableGeometry()
        self.move(geo.x() + geo.width() - self.width() - 14, geo.y() + 50)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        if self._toggle_worker is not None and self._toggle_worker.isRunning():
            self._pending_quit_after_toggle = True
            self.hide()
            event.ignore()
            return
        app = QApplication.instance()
        if app is not None:
            app.quit()
        super().closeEvent(event)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(10)

        icon = QLabel(material_icon("shield"))
        icon.setObjectName("headerIcon")
        icon.setFont(QFont(self.material_font, 20))
        self._header_icon_label = icon
        header_text = QVBoxLayout()
        header_text.setContentsMargins(0, 0, 0, 0)
        header_text.setSpacing(2)
        title = QLabel("WireGuard")
        title.setObjectName("title")
        subtitle = QLabel("Select a tunnel and bring it up or down.")
        subtitle.setObjectName("subtitle")
        header_text.addWidget(title)
        header_text.addWidget(subtitle)
        header.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
        header.addLayout(header_text, 1)

        self.close_button = create_close_button(material_icon("close"), self.material_font, font_size=18)
        self.close_button.clicked.connect(self.close)
        header.addWidget(self.close_button, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(header)

        self.state_chip = QFrame()
        self.state_chip.setObjectName("stateChip")
        chip_layout = QHBoxLayout(self.state_chip)
        chip_layout.setContentsMargins(12, 12, 12, 12)
        chip_layout.setSpacing(10)

        self.state_icon = QLabel(material_icon("lock_open"))
        self.state_icon.setObjectName("stateIcon")
        self.state_icon.setFont(QFont(self.material_font, 18))
        chip_text = QVBoxLayout()
        chip_text.setContentsMargins(0, 0, 0, 0)
        chip_text.setSpacing(2)
        self.state_label = QLabel("Checking tunnel state…")
        self.state_label.setObjectName("stateLabel")
        self.detail_label = QLabel("No interface selected")
        self.detail_label.setObjectName("detailLabel")
        chip_text.addWidget(self.state_label)
        chip_text.addWidget(self.detail_label)
        chip_layout.addWidget(self.state_icon)
        chip_layout.addLayout(chip_text, 1)
        layout.addWidget(self.state_chip)

        combo_row = QHBoxLayout()
        combo_row.setContentsMargins(0, 0, 0, 0)
        combo_row.setSpacing(8)
        combo_icon = QLabel(material_icon("tune"))
        combo_icon.setObjectName("rowIcon")
        combo_icon.setFont(QFont(self.material_font, 18))
        self._row_icon_label = combo_icon
        self.interface_combo = QComboBox()
        self.interface_combo.setObjectName("interfaceCombo")
        self.interface_combo.setView(QListView())
        self.interface_combo.currentTextChanged.connect(self._set_interface)
        combo_row.addWidget(combo_icon)
        combo_row.addWidget(self.interface_combo, 1)
        layout.addLayout(combo_row)

        self.auto_start_checkbox = QCheckBox("Auto-enable selected tunnel on session start")
        self.auto_start_checkbox.setObjectName("settingCheck")
        self.auto_start_checkbox.toggled.connect(self._toggle_auto_start)
        layout.addWidget(self.auto_start_checkbox)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)

        self.refresh_button = QPushButton(material_icon("refresh"))
        self.refresh_button.setObjectName("iconButton")
        self.refresh_button.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.refresh_button.setFont(QFont(self.material_font, 18))
        self.refresh_button.setToolTip("Refresh WireGuard configs from Hanauta service")
        self.refresh_button.clicked.connect(self._refresh_interfaces_from_service)
        self.refresh_text_button = QPushButton("Refresh configs")
        self.refresh_text_button.setObjectName("secondaryButton")
        self.refresh_text_button.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.refresh_text_button.clicked.connect(self._refresh_interfaces_from_service)

        self.toggle_button = QPushButton("Enable")
        self.toggle_button.setObjectName("primaryButton")
        self.toggle_button.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.toggle_button.clicked.connect(self._toggle_selected)

        actions.addWidget(self.refresh_button)
        actions.addWidget(self.refresh_text_button)
        actions.addWidget(self.toggle_button, 1)
        layout.addLayout(actions)

        self._build_split_tunnel_ui(layout)

        self.footer_label = QLabel("Available configurations update automatically.")
        self.footer_label.setObjectName("footerLabel")
        self.footer_label.setWordWrap(True)
        layout.addWidget(self.footer_label)

        root.addWidget(card)
        self._refresh_split_tunnel_status()
        self.style().unpolish(self.state_chip)
        self.style().polish(self.state_chip)

    def _build_split_tunnel_ui(self, layout: QVBoxLayout) -> None:
        theme = self.theme

        split_header = QLabel("Split Tunnel Configuration")
        split_header.setObjectName("sectionTitle")
        layout.addWidget(split_header)

        split_subtitle = QLabel("Configure per-app and per-domain routing. Changes apply when VPN is active.")
        split_subtitle.setObjectName("sectionSubtitle")
        split_subtitle.setWordWrap(True)
        layout.addWidget(split_subtitle)

        self.split_enabled_checkbox = QCheckBox("Enable split tunneling")
        self.split_enabled_checkbox.setObjectName("settingCheck")
        self.split_enabled_checkbox.toggled.connect(self._on_split_enabled_changed)
        layout.addWidget(self.split_enabled_checkbox)

        mode_row = QHBoxLayout()
        mode_row.setContentsMargins(0, 0, 0, 0)
        mode_row.setSpacing(8)
        mode_label = QLabel("Mode:")
        mode_label.setObjectName("detailLabel")
        mode_row.addWidget(mode_label)
        self.split_mode_combo = QComboBox()
        self.split_mode_combo.setObjectName("interfaceCombo")
        self.split_mode_combo.addItems(["Inclusive (only listed apps use VPN)", "Exclusive (listed apps bypass VPN)"])
        self.split_mode_combo.currentTextChanged.connect(self._on_split_mode_changed)
        mode_row.addWidget(self.split_mode_combo, 1)
        layout.addLayout(mode_row)

        self.kill_switch_checkbox = QCheckBox("Kill switch (block all non-VPN traffic when tunnel is up)")
        self.kill_switch_checkbox.setObjectName("settingCheck")
        self.kill_switch_checkbox.toggled.connect(self._on_kill_switch_changed)
        layout.addWidget(self.kill_switch_checkbox)

        apps_header = QLabel("App Routing")
        apps_header.setObjectName("sectionTitle")
        layout.addWidget(apps_header)

        self.apps_vpn_list = QListWidget()
        self.apps_vpn_list.setObjectName("splitList")
        self.apps_vpn_list.setMaximumHeight(100)
        layout.addWidget(QLabel("Apps forced through VPN (Inclusive mode):"))
        layout.addWidget(self.apps_vpn_list)
        apps_vpn_actions = QHBoxLayout()
        self.add_app_vpn_button = QPushButton(material_icon("add"))
        self.add_app_vpn_button.setObjectName("iconButton")
        self.add_app_vpn_button.setFont(QFont(self.material_font, 18))
        self.add_app_vpn_button.setToolTip("Add app to VPN list")
        self.add_app_vpn_button.clicked.connect(lambda: self._add_app_to_list("vpn"))
        apps_vpn_actions.addWidget(self.add_app_vpn_button)
        self.remove_app_vpn_button = QPushButton(material_icon("delete"))
        self.remove_app_vpn_button.setObjectName("iconButton")
        self.remove_app_vpn_button.setFont(QFont(self.material_font, 18))
        self.remove_app_vpn_button.setToolTip("Remove selected app")
        self.remove_app_vpn_button.clicked.connect(lambda: self._remove_app_from_list("vpn"))
        apps_vpn_actions.addWidget(self.remove_app_vpn_button)
        apps_vpn_actions.addStretch()
        layout.addLayout(apps_vpn_actions)

        self.apps_direct_list = QListWidget()
        self.apps_direct_list.setObjectName("splitList")
        self.apps_direct_list.setMaximumHeight(100)
        layout.addWidget(QLabel("Apps bypassing VPN (Exclusive mode):"))
        layout.addWidget(self.apps_direct_list)
        apps_direct_actions = QHBoxLayout()
        self.add_app_direct_button = QPushButton(material_icon("add"))
        self.add_app_direct_button.setObjectName("iconButton")
        self.add_app_direct_button.setFont(QFont(self.material_font, 18))
        self.add_app_direct_button.setToolTip("Add app to bypass list")
        self.add_app_direct_button.clicked.connect(lambda: self._add_app_to_list("direct"))
        apps_direct_actions.addWidget(self.add_app_direct_button)
        self.remove_app_direct_button = QPushButton(material_icon("delete"))
        self.remove_app_direct_button.setObjectName("iconButton")
        self.remove_app_direct_button.setFont(QFont(self.material_font, 18))
        self.remove_app_direct_button.setToolTip("Remove selected app")
        self.remove_app_direct_button.clicked.connect(lambda: self._remove_app_from_list("direct"))
        apps_direct_actions.addWidget(self.remove_app_direct_button)
        apps_direct_actions.addStretch()
        layout.addLayout(apps_direct_actions)

        domains_header = QLabel("Domain / IP Routing")
        domains_header.setObjectName("sectionTitle")
        layout.addWidget(domains_header)

        self.domains_vpn_list = QListWidget()
        self.domains_vpn_list.setObjectName("splitList")
        self.domains_vpn_list.setMaximumHeight(80)
        layout.addWidget(QLabel("Domains/IPs forced through VPN:"))
        layout.addWidget(self.domains_vpn_list)
        domains_vpn_actions = QHBoxLayout()
        self.add_domain_vpn_button = QPushButton(material_icon("add"))
        self.add_domain_vpn_button.setObjectName("iconButton")
        self.add_domain_vpn_button.setFont(QFont(self.material_font, 18))
        self.add_domain_vpn_button.setToolTip("Add domain/IP to VPN list")
        self.add_domain_vpn_button.clicked.connect(lambda: self._add_domain_to_list("vpn"))
        domains_vpn_actions.addWidget(self.add_domain_vpn_button)
        self.remove_domain_vpn_button = QPushButton(material_icon("delete"))
        self.remove_domain_vpn_button.setObjectName("iconButton")
        self.remove_domain_vpn_button.setFont(QFont(self.material_font, 18))
        self.remove_domain_vpn_button.setToolTip("Remove selected domain")
        self.remove_domain_vpn_button.clicked.connect(lambda: self._remove_domain_from_list("vpn"))
        domains_vpn_actions.addWidget(self.remove_domain_vpn_button)
        domains_vpn_actions.addStretch()
        layout.addLayout(domains_vpn_actions)

        self.domains_direct_list = QListWidget()
        self.domains_direct_list.setObjectName("splitList")
        self.domains_direct_list.setMaximumHeight(80)
        layout.addWidget(QLabel("Domains/IPs bypassing VPN:"))
        layout.addWidget(self.domains_direct_list)
        domains_direct_actions = QHBoxLayout()
        self.add_domain_direct_button = QPushButton(material_icon("add"))
        self.add_domain_direct_button.setObjectName("iconButton")
        self.add_domain_direct_button.setFont(QFont(self.material_font, 18))
        self.add_domain_direct_button.setToolTip("Add domain/IP to bypass list")
        self.add_domain_direct_button.clicked.connect(lambda: self._add_domain_to_list("direct"))
        domains_direct_actions.addWidget(self.add_domain_direct_button)
        self.remove_domain_direct_button = QPushButton(material_icon("delete"))
        self.remove_domain_direct_button.setObjectName("iconButton")
        self.remove_domain_direct_button.setFont(QFont(self.material_font, 18))
        self.remove_domain_direct_button.setToolTip("Remove selected domain")
        self.remove_domain_direct_button.clicked.connect(lambda: self._remove_domain_from_list("direct"))
        domains_direct_actions.addWidget(self.remove_domain_direct_button)
        domains_direct_actions.addStretch()
        layout.addLayout(domains_direct_actions)

        status_header = QLabel("Live Status")
        status_header.setObjectName("sectionTitle")
        layout.addWidget(status_header)

        self.split_status_label = QLabel("Split tunnel: inactive")
        self.split_status_label.setObjectName("detailLabel")
        self.split_status_label.setWordWrap(True)
        layout.addWidget(self.split_status_label)

    def _refresh_split_tunnel_status(self) -> None:
        payload = load_wireguard_cache()
        split_status = payload.get("split_tunnel", {}) if isinstance(payload, dict) else {}
        if split_status and split_status.get("enabled"):
            self.split_status_label.setText(
                f"Split tunnel: active\n"
                f"Mode: {get_split_tunnel_mode_label(split_status.get('mode', 'inclusive'))}\n"
                f"Tracked PIDs: {split_status.get('tracked_pids', 0)}\n"
                f"Active routes: {split_status.get('active_routes', 0)}\n"
                f"VPN interface: {split_status.get('vpn_interface', 'none')}"
            )
        else:
            self.split_status_label.setText("Split tunnel: inactive")

    def _load_split_config(self) -> dict[str, object]:
        return load_split_tunnel_config()

    def _apply_split_config_to_ui(self, config: dict[str, object]) -> None:
        self._building_split = True
        self.split_enabled_checkbox.setChecked(bool(config.get("enabled", False)))
        mode = str(config.get("mode", "inclusive")).lower()
        self.split_mode_combo.setCurrentIndex(0 if mode == "inclusive" else 1)
        self.kill_switch_checkbox.setChecked(bool(config.get("kill_switch", False)))
        self._populate_list(self.apps_vpn_list, config.get("apps_vpn", []))
        self._populate_list(self.apps_direct_list, config.get("apps_direct", []))
        self._populate_list(self.domains_vpn_list, config.get("domains_vpn", []))
        self._populate_list(self.domains_direct_list, config.get("domains_direct", []))
        self._building_split = False
        self._update_split_ui_state()

    def _populate_list(self, list_widget: QListWidget, items: list[str]) -> None:
        list_widget.clear()
        for item in items:
            list_widget.addItem(item)

    def _update_split_ui_state(self) -> None:
        enabled = self.split_enabled_checkbox.isChecked()
        self.split_mode_combo.setEnabled(enabled)
        self.kill_switch_checkbox.setEnabled(enabled)
        self.apps_vpn_list.setEnabled(enabled)
        self.apps_direct_list.setEnabled(enabled)
        self.domains_vpn_list.setEnabled(enabled)
        self.domains_direct_list.setEnabled(enabled)
        self.add_app_vpn_button.setEnabled(enabled)
        self.remove_app_vpn_button.setEnabled(enabled)
        self.add_app_direct_button.setEnabled(enabled)
        self.remove_app_direct_button.setEnabled(enabled)
        self.add_domain_vpn_button.setEnabled(enabled)
        self.remove_domain_vpn_button.setEnabled(enabled)
        self.add_domain_direct_button.setEnabled(enabled)
        self.remove_domain_direct_button.setEnabled(enabled)

    def _on_split_enabled_changed(self, enabled: bool) -> None:
        if getattr(self, "_building_split", False):
            return
        config = self._load_split_config()
        config["enabled"] = enabled
        self._save_and_apply_split_config(config)
        self._update_split_ui_state()

    def _on_split_mode_changed(self, text: str) -> None:
        if getattr(self, "_building_split", False):
            return
        mode = "inclusive" if "Inclusive" in text else "exclusive"
        config = self._load_split_config()
        config["mode"] = mode
        self._save_and_apply_split_config(config)

    def _on_kill_switch_changed(self, enabled: bool) -> None:
        if getattr(self, "_building_split", False):
            return
        config = self._load_split_config()
        config["kill_switch"] = enabled
        self._save_and_apply_split_config(config)

    def _add_app_to_list(self, which: str) -> None:
        if self._desktop_apps_cache is None:
            self._desktop_apps_cache = scan_desktop_apps()
        flatpak_apps = scan_flatpak_apps()
        all_apps = self._desktop_apps_cache + [{"name": a["name"], "desktop_id": a["app_id"], "comment": "", "icon_name": "", "source_path": ""} for a in flatpak_apps]
        dialog = AppSelectionDialog(
            self.theme,
            all_apps,
            title_text=f"Add app to {'VPN' if which == 'vpn' else 'bypass'} list",
            subtitle_text="Search installed apps and select one or more entries.",
            placeholder_text="Type an app name",
            add_button_text=f"Add to {'VPN' if which == 'vpn' else 'bypass'} list",
            primary_label_key="name",
            secondary_parts=("comment", "desktop_id"),
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        apps = dialog.selected_apps()
        if not apps:
            return
        config = self._load_split_config()
        target_list = config[f"apps_{which}"]
        for app in apps:
            target = app["desktop_id"]
            if target not in target_list:
                target_list.append(target)
        self._save_and_apply_split_config(config)

    def _remove_app_from_list(self, which: str) -> None:
        list_widget = self.apps_vpn_list if which == "vpn" else self.apps_direct_list
        item = list_widget.currentItem()
        if not item:
            return
        target = item.text()
        config = self._load_split_config()
        target_list = config[f"apps_{which}"]
        if target in target_list:
            target_list.remove(target)
        self._save_and_apply_split_config(config)

    def _add_domain_to_list(self, which: str) -> None:
        dialog = DomainInputDialog(self.theme, f"Add domain/IP to {'VPN' if which == 'vpn' else 'bypass'} list", self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        domain = dialog.get_domain().strip()
        if not domain:
            return
        config = self._load_split_config()
        target_list = config[f"domains_{which}"]
        if domain not in target_list:
            target_list.append(domain)
        self._save_and_apply_split_config(config)

    def _remove_domain_from_list(self, which: str) -> None:
        list_widget = self.domains_vpn_list if which == "vpn" else self.domains_direct_list
        item = list_widget.currentItem()
        if not item:
            return
        domain = item.text()
        config = self._load_split_config()
        target_list = config[f"domains_{which}"]
        if domain in target_list:
            target_list.remove(domain)
        self._save_and_apply_split_config(config)

    def _save_and_apply_split_config(self, config: dict[str, object]) -> None:
        save_split_tunnel_config(config)
        self._apply_split_config_to_ui(config)
        iface = self.interface_combo.currentText().strip()
        if iface:
            self._send_split_config_to_agent(config, iface)

    def _send_split_config_to_agent(self, config: dict[str, object], iface: str) -> None:
        payload = {
            "request_id": str(uuid.uuid4()),
            "action": "set_split_config",
            "interface": iface,
            "config": config,
            "requested_at": time.time(),
        }
        try:
            WG_AGENT_REQUEST_FILE.write_text(json.dumps(payload, ensure_ascii=True), encoding="utf-8")
        except Exception as e:
            logger.warning(f"Failed to send split config to agent: {e}")
            self.footer_label.setText(f"Failed to apply split config: {e}")

    def _apply_action_button_icons(self) -> None:
        self._apply_icon_button_svg(
            self.refresh_button, VPN_ICON_ACTION_REFRESH, "refresh", 18
        )
        self._apply_icon_button_svg(self.add_app_vpn_button, VPN_ICON_ACTION_ADD, "add", 18)
        self._apply_icon_button_svg(self.remove_app_vpn_button, VPN_ICON_ACTION_REMOVE, "delete", 18)
        self._apply_icon_button_svg(self.add_app_direct_button, VPN_ICON_ACTION_ADD, "add", 18)
        self._apply_icon_button_svg(self.remove_app_direct_button, VPN_ICON_ACTION_REMOVE, "delete", 18)
        self._apply_icon_button_svg(self.add_domain_vpn_button, VPN_ICON_ACTION_ADD, "add", 18)
        self._apply_icon_button_svg(self.remove_domain_vpn_button, VPN_ICON_ACTION_REMOVE, "delete", 18)
        self._apply_icon_button_svg(self.add_domain_direct_button, VPN_ICON_ACTION_ADD, "add", 18)
        self._apply_icon_button_svg(self.remove_domain_direct_button, VPN_ICON_ACTION_REMOVE, "delete", 18)

    def _apply_styles(self) -> None:
        theme = self.theme
        self.setStyleSheet(
            f"""
            QWidget {{
                background: transparent;
                color: {theme.text};
                font-family: "Inter", "Noto Sans", sans-serif;
                font-size: 12px;
            }}
            QFrame#card {{
                background: {theme.panel_bg};
                border: 1px solid {theme.panel_border};
                border-radius: 24px;
            }}
            QLabel#headerIcon, QLabel#rowIcon, QLabel#stateIcon {{
                color: {theme.primary};
                font-family: "{self.material_font}";
            }}
            QLabel#title {{
                color: {theme.text};
                font-size: 14px;
                font-weight: 700;
            }}
            QLabel#sectionTitle {{
                color: {theme.text};
                font-size: 12px;
                font-weight: 700;
            }}
            QLabel#sectionSubtitle {{
                color: {theme.text_muted};
                font-size: 10px;
            }}
            QLabel#subtitle, QLabel#detailLabel, QLabel#footerLabel {{
                color: {theme.text_muted};
                font-size: 10px;
            }}
            QLabel#stateLabel {{
                color: {theme.text};
                font-size: 12px;
                font-weight: 700;
            }}
            QFrame#stateChip {{
                background: {theme.chip_bg};
                border: 1px solid {theme.chip_border};
                border-radius: 20px;
            }}
            QComboBox#interfaceCombo {{
                background: {theme.chip_bg};
                border: 1px solid {theme.chip_border};
                border-radius: 14px;
                padding: 10px 12px;
                min-height: 20px;
                color: {theme.text};
                selection-background-color: {theme.hover_bg};
            }}
            QComboBox#interfaceCombo::drop-down {{
                border: none;
                width: 24px;
            }}
            QComboBox#interfaceCombo::down-arrow {{
                image: none;
                width: 0;
                height: 0;
            }}
            QComboBox#interfaceCombo QAbstractItemView {{
                background: {theme.surface_container_high};
                color: {theme.text};
                border: 1px solid {theme.chip_border};
                border-radius: 14px;
                outline: none;
                padding: 6px;
                selection-background-color: {theme.hover_bg};
                selection-color: {theme.text};
            }}
            QPushButton#iconButton {{
                background: {theme.app_running_bg};
                border: 1px solid {theme.app_running_border};
                border-radius: 14px;
                color: {theme.icon};
                font-family: "{self.material_font}";
                min-width: 42px;
                max-width: 42px;
                min-height: 42px;
                max-height: 42px;
            }}
            QPushButton#iconButton:hover {{
                background: {theme.hover_bg};
            }}
            QPushButton#primaryButton {{
                background: {theme.primary};
                border: none;
                border-radius: 14px;
                color: {theme.active_text};
                font-size: 12px;
                font-weight: 700;
                min-height: 42px;
                padding: 0 18px;
            }}
            QPushButton#primaryButton:hover {{
                background: {theme.primary_container};
                color: {theme.on_primary_container};
            }}
            QPushButton#secondaryButton, QPushButton#secondaryTextButton {{
                background: {theme.chip_bg};
                border: 1px solid {theme.chip_border};
                border-radius: 14px;
                color: {theme.text};
                min-height: 38px;
                padding: 0 14px;
            }}
            QPushButton#secondaryButton:hover, QPushButton#secondaryTextButton:hover {{
                background: {theme.hover_bg};
            }}
            QPushButton#primaryButton:disabled, QPushButton#iconButton:disabled {{
                background: {theme.app_running_bg};
                color: {theme.inactive};
                border: 1px solid {theme.app_running_border};
            }}
            QCheckBox#settingCheck {{
                color: {theme.text};
                spacing: 10px;
            }}
            QCheckBox#settingCheck::indicator {{
                width: 18px;
                height: 18px;
                border-radius: 9px;
                border: 1px solid {theme.chip_border};
                background: {theme.chip_bg};
            }}
            QCheckBox#settingCheck::indicator:checked {{
                background: {theme.primary};
                border: 1px solid {theme.primary};
            }}
            QListWidget#splitList {{
                background: {theme.chip_bg};
                border: 1px solid {theme.chip_border};
                border-radius: 16px;
                padding: 6px;
                outline: none;
            }}
            QListWidget#splitList::item {{
                padding: 10px 10px;
                margin: 2px 0;
                border-radius: 12px;
            }}
            QListWidget#splitList::item:selected {{
                background: {theme.hover_bg};
                color: {theme.text};
            }}
            QFrame#stateChip[state="active"] {{
                background: {rgba(theme.primary_container, 0.74)};
                border: 1px solid {rgba(theme.primary, 0.36)};
            }}
            QFrame#stateChip[state="error"] {{
                background: {rgba(theme.error, 0.16)};
                border: 1px solid {rgba(theme.error, 0.30)};
            }}
            """
        )
        self.style().unpolish(self.state_chip)
        self.style().polish(self.state_chip)
        self._apply_svg_icons()

    def _apply_svg_icons(self) -> None:
        color = QColor(self.theme.primary)
        if self._header_icon_label is not None:
            pix = tinted_svg_pixmap(VPN_ICON_HEADER, color, 20)
            if pix is not None:
                self._header_icon_label.setPixmap(pix)
                self._header_icon_label.setText("")
            else:
                self._header_icon_label.setPixmap(QPixmap())
                self._header_icon_label.setText(material_icon("shield"))

        if self._row_icon_label is not None:
            pix = tinted_svg_pixmap(VPN_ICON_ROW, color, 18)
            if pix is not None:
                self._row_icon_label.setPixmap(pix)
                self._row_icon_label.setText("")
            else:
                self._row_icon_label.setPixmap(QPixmap())
                self._row_icon_label.setText(material_icon("tune"))
        self._apply_action_button_icons()

    def _apply_icon_button_svg(
        self, button: QPushButton, path: Path, fallback_name: str, size: int = 18
    ) -> None:
        pix = tinted_svg_pixmap(path, QColor(self.theme.primary), size)
        if pix is not None:
            button.setIcon(QIcon(pix))
            button.setIconSize(QSize(size, size))
            button.setText("")
            return
        button.setIcon(QIcon())
        button.setText(material_icon(fallback_name))

    def _apply_action_button_icons(self) -> None:
        self._apply_icon_button_svg(
            self.refresh_button, VPN_ICON_ACTION_REFRESH, "refresh", 18
        )
        self._apply_icon_button_svg(self.add_app_vpn_button, VPN_ICON_ACTION_ADD, "add", 18)
        self._apply_icon_button_svg(self.add_app_direct_button, VPN_ICON_ACTION_ADD, "add", 18)
        self._apply_icon_button_svg(self.remove_app_vpn_button, VPN_ICON_ACTION_REMOVE, "delete", 18)
        self._apply_icon_button_svg(self.remove_app_direct_button, VPN_ICON_ACTION_REMOVE, "delete", 18)
        self._apply_icon_button_svg(self.add_domain_vpn_button, VPN_ICON_ACTION_ADD, "add", 18)
        self._apply_icon_button_svg(self.add_domain_direct_button, VPN_ICON_ACTION_ADD, "add", 18)
        self._apply_icon_button_svg(self.remove_domain_vpn_button, VPN_ICON_ACTION_REMOVE, "delete", 18)
        self._apply_icon_button_svg(self.remove_domain_direct_button, VPN_ICON_ACTION_REMOVE, "delete", 18)

    def _set_state_icon(self, path: Path, fallback_name: str) -> None:
        pix = tinted_svg_pixmap(path, QColor(self.theme.primary), 18)
        if pix is not None:
            self.state_icon.setPixmap(pix)
            self.state_icon.setText("")
            return
        self.state_icon.setPixmap(QPixmap())
        self.state_icon.setText(material_icon(fallback_name))

    def _reload_theme_if_needed(self) -> None:
        current_mtime = palette_mtime()
        if current_mtime == self._theme_mtime:
            return
        self._theme_mtime = current_mtime
        self.theme = load_theme_palette()
        self._apply_styles()

    def _refresh_interfaces_from_service(self) -> None:
        self.footer_label.setText("Refreshing WireGuard configs from Hanauta service…")
        response = wireguard_service_request("list_interfaces", timeout=8.0)
        if bool(response.get("ok", False)):
            self.footer_label.setText("WireGuard configs refreshed.")
        else:
            msg = str(response.get("message", "Failed to refresh WireGuard configs."))
            self.footer_label.setText(
                f"{msg} Reinstall VPN plugin from Marketplace to repair root agent."
            )
        self.refresh_state()

    def _load_status(self) -> dict[str, str]:
        payload = load_wireguard_cache()
        if not payload:
            return {"wireguard": "off", "wg_selected": ""}
        return {
            "wireguard": str(payload.get("wireguard", "off")),
            "wg_selected": str(payload.get("wg_selected", "")),
        }

    def _load_interfaces(self) -> list[str]:
        payload = load_wireguard_cache()
        raw_ifaces = payload.get("interfaces", [])
        if not isinstance(raw_ifaces, list):
            return []
        interfaces = [str(item).strip() for item in raw_ifaces if str(item).strip()]
        if interfaces:
            return interfaces

        now = time.time()
        if self._privileged_probe_attempted and now - self._last_privileged_probe_at < 30:
            return []
        self._privileged_probe_attempted = True
        self._last_privileged_probe_at = now
        response = wireguard_service_request("list_interfaces", timeout=6.0)
        if bool(response.get("ok", False)):
            refreshed = load_wireguard_cache()
            ifaces = refreshed.get("interfaces", []) if isinstance(refreshed, dict) else []
            interfaces = [str(item).strip() for item in ifaces if str(item).strip()]
            if interfaces:
                self.footer_label.setText("WireGuard configs refreshed from Hanauta service.")
                return interfaces
        self.footer_label.setText(str(response.get("message", "Failed to refresh WireGuard configs.")))
        return []

    def refresh_state(self) -> None:
        if self._toggle_worker is not None and self._toggle_worker.isRunning():
            return
        status = self._load_status()
        interfaces = self._load_interfaces()
        service = load_vpn_service_settings()
        selected = (
            status.get("wg_selected", "")
            or str(service.get("preferred_interface", "")).strip()
            or (interfaces[0] if interfaces else "")
        )
        active = status.get("wireguard") == "on"

        if selected and selected not in interfaces:
            interfaces.insert(0, selected)

        self._building_combo = True
        self.interface_combo.clear()
        self.interface_combo.addItems(interfaces)
        if selected:
            index = self.interface_combo.findText(selected)
            if index >= 0:
                self.interface_combo.setCurrentIndex(index)
        self.interface_combo.setEnabled(bool(interfaces))
        self._building_combo = False

        self._building_switch = True
        self.auto_start_checkbox.setChecked(bool(service.get("reconnect_on_login", False)))
        self._building_switch = False

        if not interfaces:
            self._set_state_icon(VPN_ICON_STATE_INACTIVE, "lock_open")
            self.state_label.setText("No WireGuard configs found")
            self.detail_label.setText("Expected `.conf` files in /etc/wireguard.")
            self.state_chip.setProperty("state", "inactive")
            self.toggle_button.setEnabled(False)
            self.toggle_button.setText("Enable")
            return

        self._set_state_icon(
            VPN_ICON_STATE_ACTIVE if active else VPN_ICON_STATE_INACTIVE,
            "lock" if active else "lock_open",
        )
        self.state_label.setText("Tunnel active" if active else "Tunnel inactive")
        self.detail_label.setText(f"Selected interface: {selected or interfaces[0]}")
        self.state_chip.setProperty("state", "active" if active else "inactive")
        self.toggle_button.setEnabled(True)
        self.toggle_button.setText("Disable" if active else "Enable")
        self.style().unpolish(self.state_chip)
        self.style().polish(self.state_chip)

    def _set_interface(self, iface: str) -> None:
        if self._building_combo or not iface:
            return
        save_vpn_service_setting("preferred_interface", iface)
        response = wireguard_service_request("set_interface", interface=iface, timeout=6.0)
        if not bool(response.get("ok", False)):
            self.footer_label.setText(str(response.get("message", "Failed to select interface in Hanauta service.")))
        else:
            self.footer_label.setText(f"Selected interface: {iface}")
        QTimer.singleShot(250, self.refresh_state)

    def _toggle_auto_start(self, enabled: bool) -> None:
        if self._building_switch:
            return
        iface = self.interface_combo.currentText().strip()
        if iface:
            save_vpn_service_setting("preferred_interface", iface)
        save_vpn_service_setting("reconnect_on_login", bool(enabled))
        self.footer_label.setText(
            f"{iface or 'Selected interface'} will be enabled on session start."
            if enabled
            else "Automatic WireGuard startup disabled."
        )

    def _toggle_selected(self) -> None:
        iface = self.interface_combo.currentText().strip()
        if not iface or (self._toggle_worker is not None and self._toggle_worker.isRunning()):
            return
        self.toggle_button.setEnabled(False)
        self.refresh_button.setEnabled(False)
        self.refresh_text_button.setEnabled(False)
        self.interface_combo.setEnabled(False)
        self.state_chip.setProperty("state", "inactive")
        self._set_state_icon(VPN_ICON_STATE_PENDING, "refresh")
        self.state_label.setText("Applying tunnel change…")
        self.detail_label.setText(f"Applying changes for {iface}")
        self.footer_label.setText("Sending request to Hanauta service.")
        self.style().unpolish(self.state_chip)
        self.style().polish(self.state_chip)

        self._toggle_worker = VpnToggleWorker(iface)
        self._toggle_worker.completed.connect(self._handle_toggle_finished)
        self._toggle_worker.finished.connect(self._cleanup_toggle_worker)
        self._toggle_worker.start()

    def _handle_toggle_finished(self, ok: bool, message: str) -> None:
        self.refresh_button.setEnabled(True)
        self.refresh_text_button.setEnabled(True)
        self.footer_label.setText(message)
        self.refresh_state()
        self.interface_combo.setEnabled(bool(self.interface_combo.count()))
        if not ok:
            self.state_chip.setProperty("state", "error")
            self._set_state_icon(VPN_ICON_STATE_INACTIVE, "lock_open")
            self.state_label.setText("WireGuard command failed")
            self.detail_label.setText(message)
            self.style().unpolish(self.state_chip)
            self.style().polish(self.state_chip)
        self.toggle_button.setEnabled(bool(self.interface_combo.count()))
        if self._pending_quit_after_toggle:
            self._pending_quit_after_toggle = False
            self.close()

    def _cleanup_toggle_worker(self) -> None:
        worker = self._toggle_worker
        self._toggle_worker = None
        if worker is not None:
            worker.deleteLater()


def main() -> int:
    def _log_excepthook(exc_type, exc, tb) -> None:
        append_log("Unhandled exception in vpn_control.py")
        append_log("".join(traceback.format_exception(exc_type, exc, tb)).strip())
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = _log_excepthook

    # Initialize localization (read from settings)
    settings = load_vpn_service_settings()
    lang = str(settings.get("language", "")).strip() or None
    active_lang = init_language(lang)
    append_log(f"Starting popup from {PLUGIN_ROOT} (language: {active_lang})")
    append_log(f"Python executable: {sys.executable}")
    append_log(f"argv: {sys.argv}")
    append_log(f"QtSvg available: {QSvgRenderer is not None}")
    append_log(f"DISPLAY={os.environ.get('DISPLAY', '')} WAYLAND_DISPLAY={os.environ.get('WAYLAND_DISPLAY', '')}")
    append_log(f"XDG_SESSION_TYPE={os.environ.get('XDG_SESSION_TYPE', '')}")
    if not service_enabled():
        append_log("Service disabled in settings. Exiting popup.")
        return 0
    append_log("Service enabled; creating QApplication")
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)
    app.setStyle("Fusion")

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(0, 0, 0, 0))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(255, 255, 255))
    app.setPalette(palette)

    append_log("Creating VpnControlPopup widget")
    popup = VpnControlPopup()
    append_log("Showing VpnControlPopup")
    popup.show()
    code = app.exec()
    append_log(f"QApplication exited with code {code}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
