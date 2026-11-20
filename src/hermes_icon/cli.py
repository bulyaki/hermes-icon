"""Command-line interface for hermes-icon."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
import time
from pathlib import Path

from . import __version__
from .applier import apply_icon, check_and_heal, inspect_surfaces
from .backup import restore_original_icons
from .config import (
    DEFAULT_BG_DARK,
    DEFAULT_BG_LIGHT,
    DEFAULT_FG_DARK,
    DEFAULT_FG_LIGHT,
    DEFAULT_PRESET,
    IconConfig,
    load_config,
    normalize_hex_color,
    save_config,
)
from .presets import PRESET_ORDER, PRESETS, resolve_preset_id
from .watcher import install_watcher, uninstall_watcher, watcher_status


def _cmd_list(_args: argparse.Namespace) -> int:
    cfg = load_config()
    surf = inspect_surfaces()
    active_str = (
        f"preset:{cfg.preset}" if cfg.mode == "preset" else f"custom:{cfg.custom_path}"
    )
    print(f"Active icon : {active_str} (light={cfg.bg_light}, dark={cfg.bg_dark})")
    print(f"Sync status : {surf['matching']}/{surf['total_surfaces']} surfaces synced"
          + (" [NEEDS APPLY]" if surf["needs_apply"] else " [OK]"))
    print("\nAvailable presets:")
    for idx, pid in enumerate(PRESET_ORDER, 1):
        p = PRESETS[pid]
        mark = "*" if (cfg.mode == "preset" and cfg.preset == pid) else " "
        default_tag = " (default)" if pid == DEFAULT_PRESET else ""
        print(f"  {mark} {idx}. {pid:<15s}  {p.name}{default_tag} — {p.tagline}")
    return 0


def _cmd_set(args: argparse.Namespace) -> int:
    cur = load_config()
    bg_light = normalize_hex_color(args.bg_light, cur.bg_light) if args.bg_light else cur.bg_light
    bg_dark = normalize_hex_color(args.bg_dark, cur.bg_dark) if args.bg_dark else cur.bg_dark
    fg_light = normalize_hex_color(args.fg_light, cur.fg_light) if args.fg_light else cur.fg_light
    fg_dark = normalize_hex_color(args.fg_dark, cur.fg_dark) if args.fg_dark else cur.fg_dark

    if args.reset_colors:
        bg_light, bg_dark = DEFAULT_BG_LIGHT, DEFAULT_BG_DARK
        fg_light, fg_dark = DEFAULT_FG_LIGHT, DEFAULT_FG_DARK

    if args.custom:
        custom_path = str(Path(args.custom).expanduser().resolve())
        custom_dark_path = (
            str(Path(args.custom_dark).expanduser().resolve())
            if args.custom_dark
            else None
        )
        full_bleed: bool | None = True if args.full_bleed else (False if args.no_full_bleed else None)
        new_cfg = IconConfig(
            mode="custom",
            preset=cur.preset,
            custom_path=custom_path,
            custom_dark_path=custom_dark_path,
            scale=args.scale if args.scale is not None else cur.scale,
            full_bleed=full_bleed,
            bg_light=bg_light,
            bg_dark=bg_dark,
            fg_light=fg_light,
            fg_dark=fg_dark,
        )
    else:
        if not args.preset:
            print("Error: specify a preset name or --custom <path>.", file=sys.stderr)
            return 2
        resolved_preset = resolve_preset_id(args.preset)
        if resolved_preset not in PRESETS:
            print(
                f"Error: unknown preset {args.preset!r}. Choose from: {', '.join(PRESET_ORDER)}",
                file=sys.stderr,
            )
            return 2
        new_cfg = IconConfig(
            mode="preset",
            preset=resolved_preset,
            scale=args.scale if args.scale is not None else cur.scale,
            bg_light=bg_light,
            bg_dark=bg_dark,
            fg_light=fg_light,
            fg_dark=fg_dark,
        )

    t0 = time.monotonic()
    res = apply_icon(new_cfg, refresh_dock=args.refresh_dock)
    elapsed = time.monotonic() - t0
    label = new_cfg.preset if new_cfg.mode == "preset" else new_cfg.custom_path
    target_kind = "Staged targets" if res["repo"].get("staged") else "Repo targets"
    print(f"Applied '{label}' across all surfaces in {elapsed:.2f}s:")
    print(f"  - {target_kind:<14s}: {res['repo']['targets_written']} ({res['repo']['check_stdout']})")
    if res["hermes_app"].get("patched"):
        asar = res["hermes_app"]["asar"]
        car_state = "Assets.car" if res["hermes_app"].get("assets_car_compiled", True) else "Assets.car(skipped->icon.icns)"
        print(
            f"  - Hermes.app    : {car_state}, icon.icns, icon.ico, app.asar "
            f"(packed={asar['packed_updated']}, unpacked={asar['unpacked_updated']}), codesign verified"
        )
    if res.get("windows_apps"):
        for w in res["windows_apps"]:
            print(
                f"  - Windows app   : {w['path']} "
                f"(patched={w['patched']}, msix_tiles={w.get('msix_tiles_updated', 0)})"
            )
    if sys.platform == "darwin" or res["applications_hermes_app_patched"]:
        print(f"  - /Applications/Hermes.app icon.icns patched: {res['applications_hermes_app_patched']}")
    if (
        not res["hermes_app"].get("patched")
        and not res.get("windows_apps")
        and not res["applications_hermes_app_patched"]
    ):
        print("  - Warning       : No installed Hermes desktop app bundle was found to patch.")
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    cfg = load_config()
    surf = inspect_surfaces()
    watch = watcher_status()
    payload = {
        "config": cfg.to_dict(),
        "surfaces": surf,
        "watcher": watch,
    }
    if args.json:
        print(json.dumps(payload, indent=2))
        return 0

    active = f"preset:{cfg.preset}" if cfg.mode == "preset" else f"custom:{cfg.custom_path}"
    print(f"Active icon     : {active}")
    print(f"Colors          : light={cfg.bg_light} dark={cfg.bg_dark} scale={cfg.scale}")
    print(f"Original backup : {'present' if surf['backup_present'] else 'not yet created'}")
    print(f"Watcher paused  : {'yes' if cfg.watch_paused else 'no'}")
    print(f"Surfaces        : {surf['matching']}/{surf['total_surfaces']} matching"
          + (" (NEEDS APPLY)" if surf["needs_apply"] else " (all synced)"))
    if surf["drifted"]:
        for item in surf["drifted"]:
            print(f"  - drifted: {item['surface']}")
    if surf["restored_to_original"]:
        for s in surf["restored_to_original"]:
            print(f"  - reverted to original: {s}")
    if surf["missing"]:
        for s in surf["missing"]:
            print(f"  - missing: {s}")

    if watch.get("backend") == "schtasks":
        print(f"Task Scheduler  : {watch['task_name']} ({'registered' if watch['active'] else 'not registered'})")
    elif watch.get("backend") == "launchd":
        print(f"launchd agent   : {watch['label']} ({'loaded' if watch['launchd_loaded'] else 'not loaded'})")
    else:
        print(f"Watcher backend : {watch.get('backend', 'git-hooks')}")
    hooks = ", ".join(f"{k}={'ok' if v else 'missing'}" for k, v in watch["git_hooks"].items())
    print(f"Git hooks       : {hooks}")
    return 0


def _cmd_check(args: argparse.Namespace) -> int:
    res = check_and_heal(apply_if_needed=args.apply, delay=args.delay)
    if args.json:
        print(json.dumps(res, indent=2))
    else:
        print(
            f"check: matching={res['matching']}/{res['total_surfaces']} "
            f"needs_apply={res['needs_apply']} action={res['action']}"
        )
        if res.get("reason"):
            print(f"  reason: {res['reason']}")
    if not args.apply and res["needs_apply"]:
        return 1
    return 0


def _cmd_watch(args: argparse.Namespace) -> int:
    sub = args.watch_action or "status"
    if sub == "install":
        res = install_watcher()
        if res.get("backend") == "schtasks":
            print(f"Registered Task Scheduler job: {res['task_name']} (active={res['active']})")
        elif res.get("backend") == "launchd":
            print(f"Installed launchd agent: {res['plist']} (loaded={res['launchd_loaded']})")
        else:
            print(f"Installed git-hook watcher (active={res['active']})")
        print(f"Installed git hooks  : {len(res['hooks_installed'])} ({', '.join(Path(p).name for p in res['hooks_installed'])})")
        return 0
    if sub == "uninstall":
        res = uninstall_watcher()
        print(f"Uninstalled watcher (active={res.get('active', False)})")
        return 0
    if sub == "run":
        res = check_and_heal(apply_if_needed=True)
        print(f"watch run: action={res['action']} matching={res['matching']}/{res['total_surfaces']}")
        return 0
    # status
    st = watcher_status()
    print(json.dumps(st, indent=2))
    return 0


def _cmd_restore(args: argparse.Namespace) -> int:
    cfg = load_config()
    cfg.watch_paused = True
    save_config(cfg)
    res = restore_original_icons()
    print(f"Restored {res['restored_count']} original nous-girl icon files and paused watcher.")
    print("Run 'hermes-icon set <preset>' to re-enable replacement.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hermes-icon",
        description="Replace the Hermes app nous-girl icon across all surfaces.",
    )
    parser.add_argument("-V", "--version", action="version", version=f"hermes-icon {__version__}")
    parser.add_argument(
        "--bootstrap",
        action="store_true",
        help="Ensure runtime dependencies are installed and exit",
    )

    sub = parser.add_subparsers(dest="command")

    p_list = sub.add_parser("list", help="List built-in presets and current status")
    p_list.set_defaults(func=_cmd_list)

    p_set = sub.add_parser("set", help="Apply a preset or custom icon everywhere")
    p_set.add_argument("preset", nargs="?", help="Preset ID (e.g. caduceus)")
    p_set.add_argument("--custom", help="Path to custom .svg, .png, .icns, .ico, .jpg, or .webp icon")
    p_set.add_argument("--custom-dark", help="Optional dark-mode custom icon path")
    p_set.add_argument("--scale", type=float, help="Icon scale inside squircle (0.35..1.0, default 0.78)")
    p_set.add_argument("--full-bleed", action="store_true", help="Fill squircle mask edge-to-edge (custom icons)")
    p_set.add_argument("--no-full-bleed", action="store_true", help="Always center custom icon inside squircle plate")
    p_set.add_argument("--bg-light", help="Hex background color for light squircle (default #ffffff)")
    p_set.add_argument("--bg-dark", help="Hex background color for dark squircle (default #0d1117)")
    p_set.add_argument("--fg-light", help="Hex foreground color for light preset (default #000000)")
    p_set.add_argument("--fg-dark", help="Hex foreground color for dark preset (default #ffffff)")
    p_set.add_argument("--reset-colors", action="store_true", help="Reset plate/icon colors to defaults")
    p_set.add_argument("--refresh-dock", action="store_true", help="Restart Dock & Finder to flush cached icons")
    p_set.set_defaults(func=_cmd_set)

    p_pick = sub.add_parser("pick", help="Launch interactive terminal (TUI) icon picker")
    p_pick.add_argument("--refresh-dock", action="store_true")
    def _run_pick(a: argparse.Namespace) -> int:
        from .tui import run_tui
        return run_tui(refresh_dock=a.refresh_dock)
    p_pick.set_defaults(func=_run_pick)

    p_gui = sub.add_parser("gui", help="Launch visual local web GUI picker")
    p_gui.add_argument("--port", type=int, default=0, help="Port to bind (default ephemeral)")
    p_gui.add_argument("--no-open", action="store_true", help="Do not open default browser automatically")
    p_gui.add_argument("--keep-open", action="store_true", help="Keep GUI server running after Apply")
    def _run_gui(a: argparse.Namespace) -> int:
        from .gui import run_gui
        return run_gui(port=a.port, open_browser=not a.no_open, keep_open=a.keep_open)
    p_gui.set_defaults(func=_run_gui)

    p_status = sub.add_parser("status", help="Show active icon, surface sync, and watcher status")
    p_status.add_argument("--json", action="store_true", help="Emit JSON output")
    p_status.set_defaults(func=_cmd_status)

    p_check = sub.add_parser("check", help="Check surface SHA-256 fingerprints and optionally heal")
    p_check.add_argument("--apply", action="store_true", help="Re-apply active icon if any surface reverted")
    p_check.add_argument("--delay", type=float, default=0.0, help="Optional delay in seconds before checking")
    p_check.add_argument("--json", action="store_true", help="Emit JSON output")
    p_check.set_defaults(func=_cmd_check)

    p_watch = sub.add_parser("watch", help="Manage launchd agent and git hooks watcher")
    p_watch.add_argument("watch_action", nargs="?", choices=["install", "uninstall", "status", "run"], default="status")
    p_watch.set_defaults(func=_cmd_watch)

    p_restore = sub.add_parser("restore", help="Restore original nous-girl icon and pause watcher")
    p_restore.add_argument("--refresh-dock", action="store_true")
    p_restore.set_defaults(func=_cmd_restore)

    return parser


def _init_windows_console() -> None:
    if sys.platform == "win32":
        os.system("")
        with contextlib.suppress(Exception):
            import ctypes

            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
            ctypes.windll.kernel32.SetConsoleCP(65001)
        for _stream in (sys.stdout, sys.stderr):
            if hasattr(_stream, "reconfigure"):
                with contextlib.suppress(Exception):
                    _stream.reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    _init_windows_console()
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.bootstrap:
        return 0
    if args.command is None:
        if sys.stdin.isatty() and sys.stdout.isatty():
            from .tui import run_tui
            return run_tui()
        _cmd_status(argparse.Namespace(json=False))
        print()
        parser.print_help()
        return 0
    return int(args.func(args))
