"""Configuration, paths, and state management for hermes-icon."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

APP_ROOT = Path(__file__).resolve().parents[2]
BIN_DIR = APP_ROOT / "bin"

HERMES_HOME = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
HERMES_REPO = Path(os.environ.get("HERMES_REPO", str(HERMES_HOME / "hermes-agent")))
HERMES_UPDATE_LOCK = HERMES_HOME / ".hermes-update-in-progress.lock"
HERMES_UPDATE_MARKER = HERMES_HOME / ".hermes-update-in-progress"

REPLACER_ROOT = Path(
    os.environ.get("HERMES_ICON_STATE_DIR", str(HERMES_HOME / "icon-replacer"))
)
ICON_REPLACER_DIR = REPLACER_ROOT
BACKUPS_ORIGINAL_DIR = REPLACER_ROOT / "backups" / "original"
BACKUPS_MANIFEST = BACKUPS_ORIGINAL_DIR / "manifest.json"
CUSTOM_ASSETS_DIR = REPLACER_ROOT / "custom-cache"
LOGS_DIR = REPLACER_ROOT / "logs"
CONFIG_PATH = REPLACER_ROOT / "config.json"
STATE_PATH = REPLACER_ROOT / "state.json"
REPLACER_LOCK_PATH = REPLACER_ROOT / "replacer.lock"

GENERATE_ICONS_PY = HERMES_REPO / "scripts" / "generate_icons.py"
ENTITLEMENTS_PLIST = HERMES_REPO / "apps" / "desktop" / "electron" / "entitlements.mac.plist"
WEB_DIST_FAVICON = HERMES_REPO / "hermes_cli" / "web_dist" / "favicon.ico"
REPO_WEB_FAVICON = HERMES_REPO / "web" / "public" / "favicon.ico"

HERMES_APP = HERMES_REPO / "apps" / "desktop" / "release" / "mac-arm64" / "Hermes.app"
APPLICATIONS_HERMES_APP = Path("/Applications/Hermes.app")

LAUNCHD_LABEL = "com.codeproquo.hermes-icon-replacer"
LAUNCHD_PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"

SYMLINK_LOCAL_BIN = Path.home() / ".local" / "bin" / "hermes-icon"
SYMLINK_HERMES_BIN = HERMES_HOME / "bin" / "hermes-icon"

DEFAULT_BG_LIGHT = "#ffffff"
DEFAULT_BG_DARK = "#0d1117"
DEFAULT_FG_LIGHT = "#000000"
DEFAULT_FG_DARK = "#ffffff"
DEFAULT_PRESET = "caduceus"


@dataclass
class IconConfig:
    mode: str = "preset"  # "preset" | "custom"
    preset: str = DEFAULT_PRESET
    custom_path: str | None = None
    custom_dark_path: str | None = None
    scale: float = 0.78
    full_bleed: bool | None = None  # None = auto-detect for opaque squares
    bg_light: str = DEFAULT_BG_LIGHT
    bg_dark: str = DEFAULT_BG_DARK
    fg_light: str = DEFAULT_FG_LIGHT
    fg_dark: str = DEFAULT_FG_DARK
    watch_paused: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "IconConfig":
        known = {
            "mode",
            "preset",
            "custom_path",
            "custom_dark_path",
            "scale",
            "full_bleed",
            "bg_light",
            "bg_dark",
            "fg_light",
            "fg_dark",
            "watch_paused",
        }
        kwargs = {k: v for k, v in data.items() if k in known}
        extra = {k: v for k, v in data.items() if k not in known and k != "extra"}
        if isinstance(data.get("extra"), dict):
            extra.update(data["extra"])
        return cls(**kwargs, extra=extra)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        extra = d.pop("extra", {})
        if extra:
            d["extra"] = extra
        return d


def ensure_dirs() -> None:
    for d in (
        REPLACER_ROOT,
        BACKUPS_ORIGINAL_DIR,
        CUSTOM_ASSETS_DIR,
        LOGS_DIR,
    ):
        d.mkdir(parents=True, exist_ok=True)


def load_config(path: Path = CONFIG_PATH) -> IconConfig:
    if not path.exists():
        return IconConfig()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return IconConfig.from_dict(data)
    except Exception:
        pass
    return IconConfig()


def save_config(cfg: IconConfig, path: Path = CONFIG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg.to_dict(), indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def load_state(path: Path = STATE_PATH) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_state(state: dict[str, Any], path: Path = STATE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def normalize_hex_color(value: str, fallback: str) -> str:
    s = (value or "").strip()
    if not s:
        return fallback
    if not s.startswith("#"):
        s = "#" + s
    if len(s) == 4 and all(c in "0123456789abcdefABCDEF" for c in s[1:]):
        s = "#" + "".join(c * 2 for c in s[1:])
    if len(s) == 7 and all(c in "0123456789abcdefABCDEF" for c in s[1:]):
        return s.lower()
    raise ValueError(f"Invalid hex color: {value!r}")
