"""Persistent user preferences for LagLens.

Settings live in a standalone INI file outside the project directory
(``%LOCALAPPDATA%\\LagLens\\LagLens.ini`` on Windows), so updating or
moving the source code does not lose them.

Every getter validates its value and falls back to a safe default.
The file is only read; no executable path is ever launched from here.
"""

from __future__ import annotations

import json
import os

from pathlib import Path

from PySide6.QtCore import QSettings

from i18n import LANGUAGE_MODES
import runtime_paths


PROJECT_ROOT = runtime_paths.app_dir()

CONFIG_DIR_NAME = "LagLens"
CONFIG_FILE_NAME = "LagLens.ini"
ENV_DATA_DIR = "LAGLENS_DATA_DIR"

DEFAULT_TARGET_FPS = 60
MIN_TARGET_FPS = 1
MAX_TARGET_FPS = 1000

MAX_REMEMBERED_TARGETS = 50
MAX_RECENT_CAPTURES = 8

DEFAULT_NETWORK_PUBLIC_TARGET = "1.1.1.1"

DEFAULT_TELEMETRY_INTERVAL_MS = 250
MIN_TELEMETRY_INTERVAL_MS = 100
MAX_TELEMETRY_INTERVAL_MS = 5000

LANGUAGE_KEY = "ui/language"
TARGET_FPS_KEY = "performance/target_fps"
TELEMETRY_INTERVAL_KEY = "telemetry/interval_ms"
NETWORK_PUBLIC_TARGET_KEY = "network/public_target"
SUCCESSFUL_TARGETS_KEY = "processes/successful_targets"
RECENT_CAPTURES_KEY = "captures/recent"
ONBOARDING_SEEN_KEY = "ui/onboarding_seen"
AI_PROVIDER_KEY = "ai/provider"
AI_MODEL_PREFIX = "ai/model/"


def candidate_data_dirs():
    """Return user-writable data directories in preference order.

    The normal location is ``%LOCALAPPDATA%\\LagLens``.  This keeps
    settings, captures and logs out of the application folder and works
    for non-administrator users.  ``LAGLENS_DATA_DIR`` can override the
    location for portable or test runs.
    """

    override = os.environ.get(ENV_DATA_DIR)

    if override:

        return [Path(override)]

    local_app_data = os.environ.get("LOCALAPPDATA")

    if local_app_data:

        preferred = Path(local_app_data) / CONFIG_DIR_NAME

    else:

        preferred = (
            Path.home()
            / "AppData"
            / "Local"
            / CONFIG_DIR_NAME
        )

    candidates = [
        preferred,
        Path.home() / CONFIG_DIR_NAME,
    ]

    unique = []
    seen = set()

    for path in candidates:

        marker = str(path).lower()

        if marker in seen:

            continue

        seen.add(marker)
        unique.append(path)

    return unique


def default_settings_path():
    """Return the preferred settings file path (not yet created)."""

    return (
        candidate_data_dirs()[0]
        / CONFIG_FILE_NAME
    )


def resolve_settings_path():
    """Return the first settings directory that can be created."""

    return user_data_dir() / CONFIG_FILE_NAME


def user_data_dir():
    """Return the first writable LagLens data directory."""

    for root in candidate_data_dirs():

        try:

            root.mkdir(
                parents=True,
                exist_ok=True,
            )

            return root

        except OSError:

            continue

    fallback = Path.home() / CONFIG_DIR_NAME

    fallback.mkdir(parents=True, exist_ok=True)

    return fallback


def _clean_targets(targets):
    """Validate remembered targets; never resolve or execute paths."""

    cleaned = []
    seen = set()

    if not isinstance(targets, (list, tuple)):

        return cleaned

    for item in targets:

        if not isinstance(item, dict):

            continue

        path = item.get("path")
        executable = item.get("executable")

        if not isinstance(path, str) or not path.strip():

            continue

        if (
            not isinstance(executable, str)
            or not executable.strip()
        ):

            continue

        marker = path.strip().lower()

        if marker in seen:

            continue

        seen.add(marker)

        cleaned.append(
            {
                "path": path.strip(),
                "executable": executable.strip(),
                "last_success": str(
                    item.get("last_success", "")
                ),
            }
        )

    return cleaned[:MAX_REMEMBERED_TARGETS]


def _clean_recent_captures(captures):
    """Validate recent-capture records without touching the filesystem."""

    cleaned = []
    seen = set()

    if not isinstance(captures, (list, tuple)):

        return cleaned

    for item in captures:

        if not isinstance(item, dict):

            continue

        path = item.get("path")

        if not isinstance(path, str) or not path.strip():

            continue

        marker = path.strip().lower()

        if marker in seen:

            continue

        seen.add(marker)

        try:

            frames = int(item.get("frames", 0))

        except (TypeError, ValueError):

            frames = 0

        cleaned.append(
            {
                "path": path.strip(),
                "name": str(
                    item.get("name")
                    or Path(path.strip()).name
                ),
                "target": str(
                    item.get("target", "") or ""
                ).strip(),
                "captured_at": str(
                    item.get("captured_at", "") or ""
                ),
                "frames": max(0, frames),
                "telemetry": bool(
                    item.get("telemetry", False)
                ),
            }
        )

    return cleaned[:MAX_RECENT_CAPTURES]


class AppSettings:
    """Typed access to the LagLens INI file."""

    def __init__(self, path=None):

        self.path = (
            Path(path)
            if path is not None
            else resolve_settings_path()
        )

        self.path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self._settings = QSettings(
            str(self.path),
            QSettings.Format.IniFormat,
        )

    def sync(self):

        self._settings.sync()

    # --------------------------------------
    # Language
    # --------------------------------------

    @property
    def language_mode(self):

        value = self._read_str(
            LANGUAGE_KEY,
            "system",
        )

        if value not in LANGUAGE_MODES:

            return "system"

        return value

    def set_language_mode(self, mode):

        if mode not in LANGUAGE_MODES:

            raise ValueError(
                f"Unknown language mode: {mode!r}"
            )

        self._settings.setValue(LANGUAGE_KEY, mode)
        self.sync()

    # --------------------------------------
    # Target FPS (used by Phase C)
    # --------------------------------------

    @property
    def target_fps(self):

        raw = self._settings.value(
            TARGET_FPS_KEY,
            DEFAULT_TARGET_FPS,
        )

        try:

            value = int(raw)

        except (TypeError, ValueError):

            return DEFAULT_TARGET_FPS

        if not MIN_TARGET_FPS <= value <= MAX_TARGET_FPS:

            return DEFAULT_TARGET_FPS

        return value

    @property
    def target_fps_explicit(self):
        """True when the user or a previous run stored a target.

        The default is a diagnostic reference, not an explicit user
        target, so a stable 30 FPS cap must not be reported as a
        failure merely because the default is 60.
        """

        return bool(
            self._settings.contains(TARGET_FPS_KEY)
        )

    def set_target_fps(self, value):

        value = int(value)

        if not MIN_TARGET_FPS <= value <= MAX_TARGET_FPS:

            raise ValueError(
                f"Target FPS out of range: {value}"
            )

        self._settings.setValue(TARGET_FPS_KEY, value)
        self.sync()

    # --------------------------------------
    # Network probe target
    # --------------------------------------

    @property
    def network_public_target(self):

        raw = self._settings.value(
            NETWORK_PUBLIC_TARGET_KEY,
            DEFAULT_NETWORK_PUBLIC_TARGET,
        )
        text = str(raw or "").strip()

        return text or DEFAULT_NETWORK_PUBLIC_TARGET

    def set_network_public_target(self, value):

        text = str(value or "").strip()

        if not text:

            raise ValueError(
                "network public target must not be empty"
            )

        self._settings.setValue(
            NETWORK_PUBLIC_TARGET_KEY,
            text,
        )
        self.sync()

    # --------------------------------------
    # Hardware telemetry interval (Phase C-1)
    # --------------------------------------

    @property
    def telemetry_interval_ms(self):

        raw = self._settings.value(
            TELEMETRY_INTERVAL_KEY,
            DEFAULT_TELEMETRY_INTERVAL_MS,
        )

        try:

            value = int(raw)

        except (TypeError, ValueError):

            return DEFAULT_TELEMETRY_INTERVAL_MS

        if not (
            MIN_TELEMETRY_INTERVAL_MS
            <= value
            <= MAX_TELEMETRY_INTERVAL_MS
        ):

            return DEFAULT_TELEMETRY_INTERVAL_MS

        return value

    def set_telemetry_interval_ms(self, value):

        value = int(value)

        if not (
            MIN_TELEMETRY_INTERVAL_MS
            <= value
            <= MAX_TELEMETRY_INTERVAL_MS
        ):

            raise ValueError(
                f"Telemetry interval out of range: {value}"
            )

        self._settings.setValue(
            TELEMETRY_INTERVAL_KEY,
            value,
        )
        self.sync()

    # --------------------------------------
    # Successfully captured targets (Phase B)
    # --------------------------------------

    @property
    def successful_targets(self):

        raw = self._read_str(
            SUCCESSFUL_TARGETS_KEY,
            "[]",
        )

        try:

            data = json.loads(raw)

        except (TypeError, ValueError):

            return []

        return _clean_targets(data)

    def set_successful_targets(self, targets):

        cleaned = _clean_targets(targets)

        self._settings.setValue(
            SUCCESSFUL_TARGETS_KEY,
            json.dumps(cleaned, ensure_ascii=False),
        )

        self.sync()

    # --------------------------------------
    # Recent captures (UX-4)
    # --------------------------------------

    @property
    def recent_captures(self):

        raw = self._read_str(
            RECENT_CAPTURES_KEY,
            "[]",
        )

        try:

            data = json.loads(raw)

        except (TypeError, ValueError):

            return []

        return _clean_recent_captures(data)

    def set_recent_captures(self, captures):

        cleaned = _clean_recent_captures(captures)

        self._settings.setValue(
            RECENT_CAPTURES_KEY,
            json.dumps(cleaned, ensure_ascii=False),
        )

        self.sync()

    # --------------------------------------
    # First-use onboarding
    # --------------------------------------

    @property
    def onboarding_seen(self):

        raw = self._settings.value(
            ONBOARDING_SEEN_KEY,
            False,
        )

        if isinstance(raw, bool):

            return raw

        return str(raw).strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )

    def set_onboarding_seen(self, seen):

        self._settings.setValue(
            ONBOARDING_SEEN_KEY,
            bool(seen),
        )

        self.sync()

    # --------------------------------------
    # AI provider selection
    # --------------------------------------

    def ai_provider(self):

        value = self._read_str(AI_PROVIDER_KEY, "").strip().lower()
        return value or "deepseek"

    def set_ai_provider(self, provider_id):

        value = str(provider_id or "").strip().lower()

        if not value:

            raise ValueError("AI provider is empty")

        self._settings.setValue(AI_PROVIDER_KEY, value)
        self.sync()

    def ai_model(self, provider_id):

        return self._read_str(
            AI_MODEL_PREFIX + str(provider_id or "").strip().lower(),
            "",
        ).strip()

    def set_ai_model(self, provider_id, model):

        value = str(model or "").strip()
        provider = str(provider_id or "").strip().lower()

        if not provider or not value:

            raise ValueError("AI model is empty")

        self._settings.setValue(
            AI_MODEL_PREFIX + provider,
            value,
        )
        self.sync()

    def _read_str(self, key, default):

        try:

            value = self._settings.value(
                key,
                default,
                type=str,
            )

        except (TypeError, ValueError):

            return default

        if not isinstance(value, str):

            return default

        return value
