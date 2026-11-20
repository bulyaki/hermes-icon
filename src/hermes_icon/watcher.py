"""launchd background watcher and git hook management."""

from __future__ import annotations

import os
import plistlib
import re
import stat
import subprocess
from pathlib import Path
from typing import Any

from .config import (
    BIN_DIR,
    HERMES_APP,
    HERMES_REPO,
    LAUNCHD_LABEL,
    LAUNCHD_PLIST_PATH,
    LOGS_DIR,
)

HOOK_NAMES = ("post-merge", "post-checkout", "post-rewrite")
HOOK_BEGIN = "# BEGIN hermes-icon-replacer"
HOOK_END = "# END hermes-icon-replacer"


def _launcher_bin(bin_dir: Path | None = None) -> Path:
    target_dir = bin_dir or BIN_DIR
    parts = target_dir.parts
    if "Cellar" in parts:
        idx = parts.index("Cellar")
        if idx + 1 < len(parts):
            formula_name = parts[idx + 1]
            prefix = Path(*parts[:idx])
            opt_bin = prefix / "opt" / formula_name / "bin" / "hermes-icon"
            if opt_bin.exists():
                return opt_bin
    return target_dir / "hermes-icon"


def _hook_snippet() -> str:
    bin_path = _launcher_bin()
    return (
        f"{HOOK_BEGIN}\n"
        f'if [ -x "{bin_path}" ]; then\n'
        f'  "{bin_path}" check --apply --delay 3 >/dev/null 2>&1 &\n'
        f"fi\n"
        f"{HOOK_END}\n"
    )


def build_launchd_plist() -> dict[str, Any]:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    return {
        "Label": LAUNCHD_LABEL,
        "ProgramArguments": [str(_launcher_bin()), "check", "--apply"],
        "WatchPaths": [
            str(HERMES_APP / "Contents" / "Resources"),
            str(HERMES_REPO / "assets"),
            str(HERMES_REPO / "hermes_cli" / "web_dist"),
        ],
        "StartInterval": 60,
        "ThrottleInterval": 5,
        "RunAtLoad": True,
        "StandardOutPath": str(LOGS_DIR / "watcher.out.log"),
        "StandardErrorPath": str(LOGS_DIR / "watcher.err.log"),
        "ProcessType": "Standard",
        "LowPriorityIO": False,
        "Nice": 0,
    }


def _uid() -> int:
    return os.getuid()


def is_launchd_loaded() -> bool:
    proc = subprocess.run(
        ["/bin/launchctl", "print", f"gui/{_uid()}/{LAUNCHD_LABEL}"],
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0


def install_git_hooks(repo: Path = HERMES_REPO) -> list[str]:
    hooks_dir = repo / ".git" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    snippet = _hook_snippet()
    installed: list[str] = []
    pattern = re.compile(
        rf"\n?{re.escape(HOOK_BEGIN)}.*?{re.escape(HOOK_END)}\n?",
        re.DOTALL,
    )

    for name in HOOK_NAMES:
        hook_path = hooks_dir / name
        if hook_path.exists():
            text = hook_path.read_text(encoding="utf-8")
            text = pattern.sub("\n", text).rstrip() + "\n\n" + snippet
        else:
            text = "#!/bin/sh\n\n" + snippet
        hook_path.write_text(text, encoding="utf-8")
        mode = hook_path.stat().st_mode
        hook_path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        installed.append(str(hook_path))
    return installed


def uninstall_git_hooks(repo: Path = HERMES_REPO) -> list[str]:
    hooks_dir = repo / ".git" / "hooks"
    removed: list[str] = []
    pattern = re.compile(
        rf"\n?{re.escape(HOOK_BEGIN)}.*?{re.escape(HOOK_END)}\n?",
        re.DOTALL,
    )
    for name in HOOK_NAMES:
        hook_path = hooks_dir / name
        if not hook_path.exists():
            continue
        text = hook_path.read_text(encoding="utf-8")
        if HOOK_BEGIN not in text:
            continue
        cleaned = pattern.sub("\n", text).strip()
        if not cleaned or cleaned in ("#!/bin/sh", "#!/usr/bin/env sh", "#!/bin/bash"):
            hook_path.unlink()
        else:
            hook_path.write_text(cleaned + "\n", encoding="utf-8")
        removed.append(str(hook_path))
    return removed


def git_hooks_status(repo: Path = HERMES_REPO) -> dict[str, bool]:
    hooks_dir = repo / ".git" / "hooks"
    out: dict[str, bool] = {}
    for name in HOOK_NAMES:
        p = hooks_dir / name
        out[name] = p.exists() and os.access(p, os.X_OK) and HOOK_BEGIN in p.read_text(encoding="utf-8")
    return out


def install_watcher(repo: Path = HERMES_REPO) -> dict[str, Any]:
    LAUNCHD_PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    plist_data = build_launchd_plist()
    tmp = LAUNCHD_PLIST_PATH.with_suffix(".plist.tmp")
    with tmp.open("wb") as f:
        plistlib.dump(plist_data, f, fmt=plistlib.FMT_XML, sort_keys=False)
    os.replace(tmp, LAUNCHD_PLIST_PATH)

    domain = f"gui/{_uid()}"
    # Bootout first if already loaded so updated plist takes effect
    subprocess.run(
        ["/bin/launchctl", "bootout", f"{domain}/{LAUNCHD_LABEL}"],
        capture_output=True,
        text=True,
    )
    boot = subprocess.run(
        ["/bin/launchctl", "bootstrap", domain, str(LAUNCHD_PLIST_PATH)],
        capture_output=True,
        text=True,
    )
    if boot.returncode != 0:
        # Fallback for environments where bootstrap returns non-zero
        load = subprocess.run(
            ["/bin/launchctl", "load", "-w", str(LAUNCHD_PLIST_PATH)],
            capture_output=True,
            text=True,
        )
        if load.returncode != 0:
            raise RuntimeError(
                f"Failed to load launchd agent: bootstrap={boot.stderr} load={load.stderr}"
            )

    hooks = install_git_hooks(repo)
    return {
        "plist": str(LAUNCHD_PLIST_PATH),
        "launchd_loaded": is_launchd_loaded(),
        "hooks_installed": hooks,
    }


def uninstall_watcher(repo: Path = HERMES_REPO) -> dict[str, Any]:
    domain = f"gui/{_uid()}"
    subprocess.run(
        ["/bin/launchctl", "bootout", f"{domain}/{LAUNCHD_LABEL}"],
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["/bin/launchctl", "unload", "-w", str(LAUNCHD_PLIST_PATH)],
        capture_output=True,
        text=True,
    )
    removed_plist = False
    if LAUNCHD_PLIST_PATH.exists():
        LAUNCHD_PLIST_PATH.unlink()
        removed_plist = True
    removed_hooks = uninstall_git_hooks(repo)
    return {
        "plist_removed": removed_plist,
        "launchd_loaded": is_launchd_loaded(),
        "hooks_removed": removed_hooks,
    }


def watcher_status(repo: Path = HERMES_REPO) -> dict[str, Any]:
    return {
        "label": LAUNCHD_LABEL,
        "plist_path": str(LAUNCHD_PLIST_PATH),
        "plist_exists": LAUNCHD_PLIST_PATH.exists(),
        "launchd_loaded": is_launchd_loaded(),
        "git_hooks": git_hooks_status(repo),
    }
