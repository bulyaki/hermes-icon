"""Configuration, paths, and state management for hermes-icon."""

from __future__ import annotations

import contextlib
import json
import os
import sys
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

IS_WINDOWS = sys.platform == "win32"
IS_MACOS = sys.platform == "darwin"

APP_ROOT = Path(__file__).resolve().parents[2]
BIN_DIR = APP_ROOT / "bin"


def candidate_hermes_homes(
    *,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
    platform: str | None = None,
) -> list[Path]:
    """Return candidate Hermes home directories in priority order."""
    env = environ if environ is not None else os.environ
    user_home = home if home is not None else Path.home()
    plat = platform if platform is not None else sys.platform

    candidates: list[Path] = []
    env_home = env.get("HERMES_HOME", "").strip()
    if env_home:
        candidates.append(Path(env_home).expanduser())
    if plat == "win32":
        local_app_data = env.get("LOCALAPPDATA", "").strip()
        local_base = Path(local_app_data) if local_app_data else (user_home / "AppData" / "Local")
        candidates.append(local_base / "hermes")
    candidates.append(user_home / ".hermes")

    out: list[Path] = []
    seen: set[Path] = set()
    for cand in candidates:
        if cand not in seen:
            seen.add(cand)
            out.append(cand)
    return out


def resolve_hermes_home(
    *,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
    platform: str | None = None,
) -> Path:
    """Resolve active Hermes home directory across platforms.

    On Windows, checks ``%HERMES_HOME%``, ``%LOCALAPPDATA%\\hermes``, and
    ``%USERPROFILE%\\.hermes`` in order, picking the first existing directory
    and defaulting to ``%LOCALAPPDATA%\\hermes``.
    """
    env = environ if environ is not None else os.environ
    cands = candidate_hermes_homes(environ=env, home=home, platform=platform)
    for cand in cands:
        if cand.is_dir():
            return cand
    return cands[0]


def windows_packaged_app_candidates(
    *,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> list[Path]:
    """Return standard install directories for the packaged Windows Hermes desktop app."""
    env = environ if environ is not None else os.environ
    user_home = home if home is not None else Path.home()
    local_app_data = env.get("LOCALAPPDATA", "").strip()
    local_base = Path(local_app_data) if local_app_data else (user_home / "AppData" / "Local")
    cands = [
        local_base / "Programs" / "Hermes",
        local_base / "hermes-desktop",
    ]
    program_files = env.get("ProgramFiles", "").strip()
    if program_files:
        cands.append(Path(program_files) / "Hermes")
    return cands


def discover_packaged_payload_dirs(
    *,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
    platform: str | None = None,
) -> list[Path]:
    """Return existing packaged desktop ``agent-payload`` directories."""
    env = environ if environ is not None else os.environ
    user_home = home if home is not None else Path.home()
    plat = platform if platform is not None else sys.platform

    candidates: list[Path] = []
    if plat == "win32":
        for app_dir in windows_packaged_app_candidates(environ=env, home=user_home):
            candidates.append(app_dir / "resources" / "agent-payload")
        program_files = env.get("ProgramFiles", "").strip()
        if program_files:
            win_apps = Path(program_files) / "WindowsApps"
            with contextlib.suppress(OSError):
                if win_apps.is_dir():
                    for pkg in sorted(win_apps.glob("NousResearch.Hermes*")):
                        candidates.append(pkg / "app" / "resources" / "agent-payload")
                        candidates.append(pkg / "resources" / "agent-payload")
    elif plat == "darwin":
        candidates.extend(
            [
                Path("/Applications/Hermes.app/Contents/Resources/agent-payload"),
                user_home / "Applications" / "Hermes.app" / "Contents" / "Resources" / "agent-payload",
            ]
        )

    found: list[Path] = []
    seen: set[Path] = set()
    for cand in candidates:
        if cand not in seen and cand.is_dir():
            seen.add(cand)
            found.append(cand)
    return found


def resolve_hermes_repo(
    hermes_home: Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
    platform: str | None = None,
) -> Path:
    """Resolve the Hermes repository checkout if present on disk."""
    env = environ if environ is not None else os.environ
    env_repo = env.get("HERMES_REPO", "").strip()
    if env_repo:
        return Path(env_repo).expanduser()

    for cand_home in candidate_hermes_homes(environ=env, home=home, platform=platform):
        cand_repo = cand_home / "hermes-agent"
        if cand_repo.is_dir():
            return cand_repo

    for payload_dir in discover_packaged_payload_dirs(environ=env, home=home, platform=platform):
        cand_repo = payload_dir / "repo"
        if cand_repo.is_dir():
            return cand_repo

    base_home = hermes_home or resolve_hermes_home(environ=env, home=home, platform=platform)
    return base_home / "hermes-agent"


def resolve_replacer_root(
    hermes_home: Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
    platform: str | None = None,
) -> Path:
    """Resolve hermes-icon runtime state directory."""
    env = environ if environ is not None else os.environ
    override = env.get("HERMES_ICON_STATE_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    base_home = hermes_home or resolve_hermes_home(environ=env, home=home, platform=platform)
    return base_home / "icon-replacer"


HERMES_HOME = resolve_hermes_home()
HERMES_REPO = resolve_hermes_repo(HERMES_HOME)
HERMES_UPDATE_LOCK = HERMES_HOME / ".hermes-update-in-progress.lock"
HERMES_UPDATE_MARKER = HERMES_HOME / ".hermes-update-in-progress"

REPLACER_ROOT = resolve_replacer_root(HERMES_HOME)
ICON_REPLACER_DIR = REPLACER_ROOT
BACKUPS_ORIGINAL_DIR = REPLACER_ROOT / "backups" / "original"
BACKUPS_MANIFEST = BACKUPS_ORIGINAL_DIR / "manifest.json"
CUSTOM_ASSETS_DIR = REPLACER_ROOT / "custom-cache"
STAGED_REPO_DIR = REPLACER_ROOT / "staged-repo"
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


def discover_windows_app_dirs(
    repo: Path = HERMES_REPO,
    *,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> list[Path]:
    """Return unpacked Windows Electron desktop app directories containing resources/app.asar or Hermes.exe."""
    env = environ if environ is not None else os.environ
    user_home = home if home is not None else Path.home()
    candidates: list[Path] = [
        repo / "apps" / "desktop" / "release" / "win-unpacked",
        repo / "apps" / "desktop" / "release" / "win-arm64-unpacked",
        repo / "apps" / "desktop" / "release" / "win-ia32-unpacked",
    ]
    for cand_home in candidate_hermes_homes(environ=env, home=user_home, platform="win32"):
        rel_dir = cand_home / "hermes-agent" / "apps" / "desktop" / "release"
        candidates.extend(
            [
                rel_dir / "win-unpacked",
                rel_dir / "win-arm64-unpacked",
                rel_dir / "win-ia32-unpacked",
            ]
        )
    candidates.extend(windows_packaged_app_candidates(environ=env, home=user_home))

    found: list[Path] = []
    seen: set[Path] = set()
    for cand in candidates:
        if cand in seen or not cand.is_dir():
            continue
        if (cand / "resources" / "app.asar").exists() or (cand / "Hermes.exe").exists():
            seen.add(cand)
            found.append(cand)
    return found

LAUNCHD_LABEL = "com.codeproquo.hermes-icon-replacer"
LAUNCHD_PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"

SYMLINK_LOCAL_BIN = Path.home() / ".local" / "bin" / "hermes-icon"
SYMLINK_HERMES_BIN = HERMES_HOME / "bin" / "hermes-icon"

DEFAULT_BG_LIGHT = "#ffffff"
DEFAULT_BG_DARK = "#0d1117"
DEFAULT_FG_LIGHT = "#000000"
DEFAULT_FG_DARK = "#ffffff"
DEFAULT_PRESET = "disco-girl"


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
