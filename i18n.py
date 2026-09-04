#!/usr/bin/env python3
from __future__ import annotations

import gettext
import locale
import os
from pathlib import Path
from typing import Optional

LOCALES_DIR = Path(__file__).resolve().parent / "locales"

_current_language: str = "en_US"
_translator: Optional[gettext.GNUTranslations] = None


def get_supported_languages() -> dict[str, str]:
    """Return dict of language_code -> display_name."""
    return {
        "en_US": "English (US)",
        "pt_BR": "Português (Brasil)",
        "ru_RU": "Русский",
        "es_AR": "Español (Argentina)",
    }


def get_current_language() -> str:
    return _current_language


def set_language(lang_code: str) -> bool:
    """Set the current language. Returns True if successful."""
    global _current_language, _translator

    if lang_code not in get_supported_languages():
        return False

    try:
        if lang_code == "en_US":
            _translator = None
        else:
            _translator = gettext.translation(
                "vpn_control",
                localedir=str(LOCALES_DIR),
                languages=[lang_code],
                fallback=True,
            )
        _current_language = lang_code
        return True
    except Exception:
        return False


def _gettext(message: str) -> str:
    if _translator:
        return _translator.gettext(message)
    return message


def ngettext(singular: str, plural: str, n: int) -> str:
    if _translator:
        return _translator.ngettext(singular, plural, n)
    return singular if n == 1 else plural


def pgettext(context: str, message: str) -> str:
    if _translator:
        return _translator.pgettext(context, message)
    return message


def detect_system_language() -> str:
    """Detect system language and return best match."""
    try:
        sys_lang, _ = locale.getdefaultlocale()
        if sys_lang:
            sys_lang = sys_lang.replace("-", "_")
            supported = get_supported_languages()
            if sys_lang in supported:
                return sys_lang
            base = sys_lang.split("_")[0]
            for code in supported:
                if code.startswith(base + "_"):
                    return code
    except Exception:
        pass
    return "en_US"


def init_language(config_lang: Optional[str] = None) -> str:
    """Initialize language from config or system. Returns the language code used."""
    lang = config_lang or detect_system_language()
    set_language(lang)
    return lang


def _(message: str) -> str:
    """Main translation function. Use as: _('Hello')"""
    return _gettext(message)


def N_(message: str) -> str:
    """No-op for marking strings for extraction. Use as: N_('Hello')"""
    return message