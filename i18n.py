"""Lightweight internationalization for LagLens.

The application uses flat JSON message catalogs instead of Qt's
.ts/.qm files because the UI is built imperatively and strings are
rendered dynamically.  A single manager owns the active language and
emits a signal so that existing windows can re-render without a
restart.

Key rules:

* catalog keys are flat strings (``tab.hardware``)
* values are UTF-8 text with ``{name}`` placeholders
* a missing translation falls back to English, then to the key itself
* a malformed catalog never prevents the application from starting
* technical identifiers (FPS, CPU, GPU, file names, paths) are never
  translated by this module
"""

from __future__ import annotations

import json
import logging
import os

from pathlib import Path

from PySide6.QtCore import (
    QLibraryInfo,
    QLocale,
    QObject,
    QTranslator,
    Signal,
)

import runtime_paths


logger = logging.getLogger("laglens.i18n")

# Avoid the logging "last resort" handler when no application handler
# is configured (for example in unit tests).  Production configures
# the parent "laglens" logger and propagation still applies.
logger.addHandler(logging.NullHandler())

DEFAULT_LOCALE_DIR = runtime_paths.resource_path(
    "locales"
)

# Languages that have a catalog file.
CATALOG_LANGUAGES = ("en", "zh_CN")

# Values accepted by the language preference.
LANGUAGE_MODES = ("system", "zh_CN", "en")

_ENV_OVERRIDE = "LAGLENS_LANGUAGE"


def normalize_language(value):
    """Map a user/Qt locale string to a supported catalog language.

    Only explicitly Simplified Chinese locales are mapped to zh_CN.
    Traditional Chinese locales (zh_TW, zh_HK, zh_MO, zh_Hant...) and
    the ambiguous bare "zh" fall back to English.  Users can still
    choose Simplified Chinese manually.
    """

    text = (value or "").strip().replace("-", "_").lower()

    if not text:

        return None

    if text.startswith("en"):

        return "en"

    if text.startswith("zh"):

        if text in ("zh_cn", "zh_sg"):

            return "zh_CN"

        if text.startswith("zh_hans"):

            return "zh_CN"

        return None

    return None


def windows_display_language():
    """Return the Windows UI display language (e.g. ``zh-CN``).

    ``QLocale.system()`` follows the regional format, which can differ
    from the language Windows itself displays.  ``GetUserDefaultUILanguage``
    is the display-language API, so prefer it.
    """

    if os.name != "nt":

        return None

    try:

        import ctypes

        from ctypes import wintypes

        kernel32 = ctypes.WinDLL(
            "kernel32",
            use_last_error=True,
        )

        kernel32.GetUserDefaultUILanguage.restype = (
            wintypes.WORD
        )

        kernel32.LCIDToLocaleName.argtypes = [
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.c_int,
            wintypes.DWORD,
        ]

        kernel32.LCIDToLocaleName.restype = (
            ctypes.c_int
        )

        langid = kernel32.GetUserDefaultUILanguage()

        if not langid:

            return None

        buffer = ctypes.create_unicode_buffer(85)

        if not kernel32.LCIDToLocaleName(
            langid,
            buffer,
            len(buffer),
            0,
        ):

            return None

        return buffer.value or None

    except (AttributeError, OSError, ValueError):

        return None


def detect_system_language():
    """Windows display language first, Qt locale as the fallback."""

    return (
        windows_display_language()
        or QLocale.system().name()
    )


def resolve_language(mode, system_locale=None):
    """Resolve a stored mode to ``en`` or ``zh_CN``.

    ``system_locale`` is injectable so tests do not depend on the
    machine's Windows display language.
    """

    if mode in ("en", "zh_CN"):

        return mode

    if mode != "system":

        raise ValueError(
            f"Unknown language mode: {mode!r}"
        )

    if system_locale is None:

        system_locale = detect_system_language()

    return normalize_language(system_locale) or "en"


def load_catalog(path):
    """Load one JSON catalog; return {} on any problem."""

    path = Path(path)

    try:

        data = json.loads(
            path.read_text(encoding="utf-8")
        )

    except (OSError, ValueError) as error:

        logger.warning(
            "Could not load translation catalog %s: %s",
            path,
            error,
        )

        return {}

    if not isinstance(data, dict):

        logger.warning(
            "Translation catalog %s is not a JSON object",
            path,
        )

        return {}

    return {
        str(key): value
        for key, value in data.items()
        if isinstance(value, str)
    }


def placeholder_names(text):
    """Return placeholder names in a catalog string."""

    import re

    return set(
        re.findall(
            r"\{([A-Za-z_][A-Za-z0-9_]*)(?::[^}]*)?\}",
            text,
        )
    )


class LanguageManager(QObject):
    """Owns the active language and the loaded catalogs."""

    language_changed = Signal(str)

    def __init__(
        self,
        env=None,
        catalog_dir=None,
    ):

        super().__init__()

        self._catalog_dir = Path(
            catalog_dir or DEFAULT_LOCALE_DIR
        )

        self._catalogs = {
            language: load_catalog(
                self._catalog_dir / f"{language}.json"
            )
            for language in CATALOG_LANGUAGES
        }

        self._language = "en"
        self._mode = "system"
        self._missing_keys = set()

        environment = os_environ(env)

        override = normalize_language(
            environment.get(_ENV_OVERRIDE)
        )

        if override:

            self._language = override

    @property
    def language(self):

        return self._language

    @property
    def mode(self):

        return self._mode

    def available_languages(self):

        return CATALOG_LANGUAGES

    def catalog(self, language=None):

        return dict(
            self._catalogs.get(
                language or self._language,
                {},
            )
        )

    def set_mode(self, mode, system_locale=None):
        """Apply a stored preference and emit the change signal."""

        if mode not in LANGUAGE_MODES:

            raise ValueError(
                f"Unknown language mode: {mode!r}"
            )

        language = resolve_language(
            mode,
            system_locale=system_locale,
        )

        changed = language != self._language

        self._mode = mode
        self._language = language

        if changed:

            self.language_changed.emit(language)

        return language

    def set_language(self, language):

        if language not in ("en", "zh_CN"):

            raise ValueError(
                f"Unknown language: {language!r}"
            )

        return self.set_mode(language)

    def translate(self, key, **kwargs):
        """Look up a key and interpolate named placeholders."""

        text = self._lookup(key)

        if not kwargs:

            return text

        try:

            return text.format(**kwargs)

        except (KeyError, IndexError, ValueError) as error:

            logger.warning(
                "Bad placeholders for %s: %s",
                key,
                error,
            )

            return text

    def _lookup(self, key):

        current = self._catalogs.get(
            self._language,
            {},
        )

        text = current.get(key)

        if text is not None:

            return text

        english = self._catalogs.get("en", {})

        fallback = english.get(key)

        if fallback is not None:

            self._log_missing(
                self._language,
                key,
                "missing translation; using English",
            )

            return fallback

        self._log_missing(
            self._language,
            key,
            "missing key",
        )

        return key

    def _log_missing(self, language, key, reason):

        marker = (language, key)

        if marker in self._missing_keys:

            return

        self._missing_keys.add(marker)

        logger.warning(
            "Translation %s [%s]: %s",
            key,
            language,
            reason,
        )


def os_environ(env):

    if env is not None:

        return env

    import os

    return os.environ


_qt_translator = None


def install_qt_translator(app, language):
    """Translate Qt's own standard strings (file dialog buttons...).

    Qt's catalogs are separate from LagLens' JSON catalogs.  Only
    Simplified Chinese is installed; English is Qt's default.
    """

    global _qt_translator

    if app is None:

        return

    if _qt_translator is not None:

        try:

            app.removeTranslator(_qt_translator)

        except (AttributeError, RuntimeError):

            pass

        _qt_translator = None

    if language != "zh_CN":

        return

    try:

        translator = QTranslator(app)

        translations = QLibraryInfo.path(
            QLibraryInfo.LibraryPath.TranslationsPath
        )

        if translator.load(
            "qtbase_zh_CN",
            translations,
        ):

            app.installTranslator(translator)
            _qt_translator = translator

    except (OSError, RuntimeError):

        pass


_manager = None


def get_manager():
    """Lazily create the process-wide manager."""

    global _manager

    if _manager is None:

        _manager = LanguageManager()

    return _manager


def tr(key, **kwargs):
    """Shortcut used by UI code."""

    return get_manager().translate(key, **kwargs)
