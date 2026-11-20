"""Cross-platform background watcher (launchd on macOS, Task Scheduler on Windows) and git hooks."""

from __future__ import annotations

import os
import plistlib
import re
import stat
import subprocess
import sys
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
WINDOWS_TASK_NAME = "HermesIconReplacer"


def _launcher_bin(bin_dir: Path | None = None, *, platform: str | None = None) -> Path:
    target_dir = bin_dir or BIN_DIR
    plat = platform or sys.platform
    if plat == "win32":
        lower_parts = [p.lower() for p in target_dir.parts]
        if "scoop" in lower_parts and "apps" in lower_parts:
            idx = lower_parts.index("apps")
            if idx + 1 < len(target_dir.parts):
                scoop_current = Path(*target_dir.parts[: idx + 2]) / "current" / "bin" / "hermes-icon.cmd"
                if scoop_current.exists():
                    return scoop_current
        cmd = target_dir / "hermes-icon.cmd"
        if cmd.exists() or platform == "win32":
            return cmd

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
    if sys.platform == "win32":
        bin_cmd = str(_launcher_bin(platform="win32")).replace("\\", "/")
        return (
            f"{HOOK_BEGIN}\n"
            f'if [ -f "{bin_cmd}" ]; then\n'
            f'  cmd.exe //c "{bin_cmd}" check --apply --delay 3 >/dev/null 2>&1 &\n'
            f"fi\n"
            f"{HOOK_END}\n"
        )
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


def build_windows_schtasks_create_cmd(launcher: Path | None = None) -> list[str]:
    bin_path = launcher or _launcher_bin(platform="win32")
    return [
        "schtasks",
        "/Create",
        "/TN",
        WINDOWS_TASK_NAME,
        "/TR",
        f'"{bin_path}" check --apply',
        "/SC",
        "MINUTE",
        "/MO",
        "1",
        "/F",
    ]


def build_windows_schtasks_query_cmd() -> list[str]:
    return ["schtasks", "/Query", "/TN", WINDOWS_TASK_NAME]


def build_windows_schtasks_delete_cmd() -> list[str]:
    return ["schtasks", "/Delete", "/TN", WINDOWS_TASK_NAME, "/F"]


def _uid() -> int:
    return os.getuid() if hasattr(os, "getuid") else 0


def is_launchd_loaded() -> bool:
    if sys.platform != "darwin":
        return False
    proc = subprocess.run(
        ["/bin/launchctl", "print", f"gui/{_uid()}/{LAUNCHD_LABEL}"],
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0


def is_windows_task_registered() -> bool:
    if sys.platform != "win32":
        return False
    proc = subprocess.run(
        build_windows_schtasks_query_cmd(),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0


def install_git_hooks(repo: Path = HERMES_REPO) -> list[str]:
    git_dir = repo / ".git"
    hooks_dir = git_dir / "hooks"
    if not git_dir.is_dir() or not os.access(git_dir, os.W_OK):
        return []
    if hooks_dir.exists() and not os.access(hooks_dir, os.W_OK):
        return []
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
        if sys.platform != "win32":
            mode = hook_path.stat().st_mode
            hook_path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        installed.append(str(hook_path))
    return installed


def uninstall_git_hooks(repo: Path = HERMES_REPO) -> list[str]:
    hooks_dir = repo / ".git" / "hooks"
    if not hooks_dir.exists():
        return []
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
        exists = p.exists()
        is_exec = True if sys.platform == "win32" else (exists and os.access(p, os.X_OK))
        out[name] = exists and is_exec and HOOK_BEGIN in p.read_text(encoding="utf-8")
    return out


def install_watcher(repo: Path = HERMES_REPO) -> dict[str, Any]:
    hooks = install_git_hooks(repo)

    if sys.platform == "win32":
        proc = subprocess.run(
            build_windows_schtasks_create_cmd(),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"Failed to register Task Scheduler job: {proc.stdout}\n{proc.stderr}")
        reg = is_windows_task_registered()
        return {
            "backend": "schtasks",
            "task_name": WINDOWS_TASK_NAME,
            "active": reg,
            "launchd_loaded": False,
            "hooks_installed": hooks,
        }

    if sys.platform != "darwin":
        return {
            "backend": "git-hooks",
            "active": bool(hooks),
            "launchd_loaded": False,
            "hooks_installed": hooks,
        }

    LAUNCHD_PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    plist_data = build_launchd_plist()
    tmp = LAUNCHD_PLIST_PATH.with_suffix(".plist.tmp")
    with tmp.open("wb") as f:
        plistlib.dump(plist_data, f, fmt=plistlib.FMT_XML, sort_keys=False)
    os.replace(tmp, LAUNCHD_PLIST_PATH)

    domain = f"gui/{_uid()}"
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
        load = subprocess.run(
            ["/bin/launchctl", "load", "-w", str(LAUNCHD_PLIST_PATH)],
            capture_output=True,
            text=True,
        )
        if load.returncode != 0:
            raise RuntimeError(
                f"Failed to load launchd agent: bootstrap={boot.stderr} load={load.stderr}"
            )

    loaded = is_launchd_loaded()
    return {
        "backend": "launchd",
        "plist": str(LAUNCHD_PLIST_PATH),
        "active": loaded,
        "launchd_loaded": loaded,
        "hooks_installed": hooks,
    }


def uninstall_watcher(repo: Path = HERMES_REPO) -> dict[str, Any]:
    removed_hooks = uninstall_git_hooks(repo)

    if sys.platform == "win32":
        subprocess.run(
            build_windows_schtasks_delete_cmd(),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
        )
        return {
            "backend": "schtasks",
            "task_name": WINDOWS_TASK_NAME,
            "active": is_windows_task_registered(),
            "plist_removed": False,
            "launchd_loaded": False,
            "hooks_removed": removed_hooks,
        }

    if sys.platform != "darwin":
        return {
            "backend": "git-hooks",
            "active": False,
            "plist_removed": False,
            "launchd_loaded": False,
            "hooks_removed": removed_hooks,
        }

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
    return {
        "backend": "launchd",
        "plist_removed": removed_plist,
        "active": is_launchd_loaded(),
        "launchd_loaded": is_launchd_loaded(),
        "hooks_removed": removed_hooks,
    }


def watcher_status(repo: Path = HERMES_REPO) -> dict[str, Any]:
    hooks = git_hooks_status(repo)
    if sys.platform == "win32":
        reg = is_windows_task_registered()
        return {
            "backend": "schtasks",
            "task_name": WINDOWS_TASK_NAME,
            "active": reg,
            "launchd_loaded": False,
            "git_hooks": hooks,
        }
    if sys.platform == "darwin":
        loaded = is_launchd_loaded()
        return {
            "backend": "launchd",
            "label": LAUNCHD_LABEL,
            "plist_path": str(LAUNCHD_PLIST_PATH),
            "plist_exists": LAUNCHD_PLIST_PATH.exists(),
            "active": loaded,
            "launchd_loaded": loaded,
            "git_hooks": hooks,
        }
    return {
        "backend": "git-hooks",
        "active": all(hooks.values()),
        "launchd_loaded": False,
        "git_hooks": hooks,
    }
