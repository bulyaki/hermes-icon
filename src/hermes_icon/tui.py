"""Interactive terminal (TUI) picker for hermes-icon."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import termios
import time
import tty
from pathlib import Path

from PIL import Image

from .applier import apply_icon
from .config import IconConfig, load_config
from .presets import PRESET_ORDER, PRESETS
from .renderer import IconRenderer

LEFT_COL_WIDTH = 44
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _visible_len(s: str) -> int:
    return len(_ANSI_RE.sub("", s))


def _read_key(fd: int) -> str:
    ch = os.read(fd, 1).decode("utf-8", errors="ignore")
    if ch == "\x1b":
        # Check for ANSI escape sequence (arrow keys)
        old_flags = termios.tcgetattr(fd)
        new_flags = list(old_flags)
        new_flags[6][termios.VMIN] = 0
        new_flags[6][termios.VTIME] = 1
        termios.tcsetattr(fd, termios.TCSANOW, new_flags)
        try:
            seq = os.read(fd, 4).decode("utf-8", errors="ignore")
        finally:
            termios.tcsetattr(fd, termios.TCSANOW, old_flags)
        if seq.startswith("[A"):
            return "UP"
        if seq.startswith("[B"):
            return "DOWN"
        return "ESC"
    if ch in ("\r", "\n"):
        return "ENTER"
    if ch == "\x03":
        return "QUIT"
    return ch


def _img_to_halfblock_rows(img: Image.Image, cols: int, rows: int) -> list[str]:
    """Convert an RGBA image to ``rows`` lines of 24-bit ANSI half-block (▀) pixels."""
    down = img.resize((cols, rows * 2), Image.LANCZOS)
    px = down.load()
    bg_r, bg_g, bg_b = 24, 26, 32
    lines: list[str] = []
    for y in range(0, rows * 2, 2):
        row_chars: list[str] = []
        for x in range(cols):
            r1, g1, b1, a1 = px[x, y]
            r2, g2, b2, a2 = px[x, y + 1]
            r1 = round(r1 * a1 / 255 + bg_r * (1 - a1 / 255))
            g1 = round(g1 * a1 / 255 + bg_g * (1 - a1 / 255))
            b1 = round(b1 * a1 / 255 + bg_b * (1 - a1 / 255))
            r2 = round(r2 * a2 / 255 + bg_r * (1 - a2 / 255))
            g2 = round(g2 * a2 / 255 + bg_g * (1 - a2 / 255))
            b2 = round(b2 * a2 / 255 + bg_b * (1 - a2 / 255))
            row_chars.append(f"\x1b[38;2;{r1};{g1};{b1}m\x1b[48;2;{r2};{g2};{b2}m▀")
        lines.append("".join(row_chars) + "\x1b[0m")
    return lines


def _render_ansi_preview(
    preset_id: str,
    cfg: IconConfig,
    *,
    term_cols: int | None = None,
) -> list[str]:
    """Render a crisp 24-bit ANSI half-block preview (side-by-side Light+Dark when wide)."""
    if term_cols is None:
        term_cols = shutil.get_terminal_size((100, 30)).columns

    preview_scale = min(0.84, max(cfg.scale, 0.80))
    temp_cfg = IconConfig(
        mode="preset",
        preset=preset_id,
        bg_light=cfg.bg_light,
        bg_dark=cfg.bg_dark,
        fg_light=cfg.fg_light,
        fg_dark=cfg.fg_dark,
        scale=preview_scale,
    )
    renderer = IconRenderer(temp_cfg)
    light_256 = renderer.render_squircle(256, dark=False, mac_grid=False)

    if term_cols >= 116:
        cols, rows = 36, 18
        dark_256 = renderer.render_squircle(256, dark=True, mac_grid=False)
        light_rows = _img_to_halfblock_rows(light_256, cols, rows)
        dark_rows = _img_to_halfblock_rows(dark_256, cols, rows)
        header = f"\x1b[2m{'Light':<{cols}s}\x1b[0m   \x1b[2m{'Dark':<{cols}s}\x1b[0m"
        return [header] + [f"{l}   {d}" for l, d in zip(light_rows, dark_rows)]

    cols, rows = 36, 18
    return _img_to_halfblock_rows(light_256, cols, rows)


def render_tui_frame(
    cfg: IconConfig,
    selected_idx: int,
    preview_cache: dict[str, list[str]],
    status_msg: str = "",
    *,
    term_cols: int | None = None,
) -> str:
    """Build the full TUI frame string with deterministic LEFT_COL_WIDTH alignment."""
    pid = PRESET_ORDER[selected_idx]
    if pid not in preview_cache:
        preview_cache[pid] = _render_ansi_preview(pid, cfg, term_cols=term_cols)
    preview = preview_cache[pid]

    out: list[str] = [
        "\x1b[2J\x1b[H",
        "\x1b[1;36m  hermes-icon\x1b[0m  —  Replace the Hermes app icon everywhere\n",
    ]
    cur_label = (
        f"preset:{cfg.preset}" if cfg.mode == "preset" else f"custom:{Path(cfg.custom_path or '').name}"
    )
    out.append(
        f"  Active: \x1b[1;33m{cur_label}\x1b[0m    "
        f"Colors: light={cfg.bg_light} dark={cfg.bg_dark}\n\n"
    )

    max_rows = max(len(PRESET_ORDER), len(preview))
    for i in range(max_rows):
        if i < len(PRESET_ORDER):
            p_id = PRESET_ORDER[i]
            preset = PRESETS[p_id]
            is_sel = i == selected_idx
            is_act = cfg.mode == "preset" and cfg.preset == p_id
            mark = "▸" if is_sel else " "
            badge = " \x1b[32m(active)\x1b[0m" if is_act else ""
            if is_sel:
                left = f"  \x1b[1;36m{mark} {i + 1}. {preset.name:<22s}\x1b[0m{badge}"
            else:
                left = f"  {mark} {i + 1}. {preset.name:<22s}{badge}"
        else:
            left = ""

        pad = " " * max(2, LEFT_COL_WIDTH - _visible_len(left))
        right = preview[i] if i < len(preview) else ""
        out.append(f"{left}{pad}{right}\n")

    sel_preset = PRESETS[pid]
    out.append(f"\n  \x1b[1m{sel_preset.name}\x1b[0m — {sel_preset.description}\n")
    out.append(
        f"\n  \x1b[2m[↑/↓ or 1-{len(PRESET_ORDER)}]\x1b[0m Select   "
        "\x1b[2m[Enter]\x1b[0m Apply   "
        "\x1b[2m[f]\x1b[0m Finder picker   "
        "\x1b[2m[c]\x1b[0m Custom path   "
        "\x1b[2m[g]\x1b[0m Web GUI   "
        "\x1b[2m[q]\x1b[0m Quit\n"
    )
    if status_msg:
        out.append(f"\n  \x1b[33m{status_msg}\x1b[0m\n")
    return "".join(out)


def _pick_file_via_finder() -> str | None:
    script = (
        'POSIX path of (choose file of type '
        '{"public.svg-image", "public.png", "com.apple.icns", "public.jpeg", "org.webmproject.webp"} '
        'with prompt "Choose a custom Hermes icon")'
    )
    proc = subprocess.run(["/usr/bin/osascript", "-e", script], capture_output=True, text=True)
    if proc.returncode == 0 and proc.stdout.strip():
        return proc.stdout.strip()
    return None


def _apply_with_progress(new_cfg: IconConfig, label: str, refresh_dock: bool) -> int:
    print(f"\nApplying '{label}' across all Hermes surfaces:")
    t0 = time.monotonic()

    def _progress(step: int, total: int, msg: str) -> None:
        print(f"  [{step}/{total}] {msg}", flush=True)

    res = apply_icon(new_cfg, refresh_dock=refresh_dock, progress_cb=_progress)
    elapsed = time.monotonic() - t0
    print(
        f"Done in {elapsed:.2f}s! {res['repo']['targets_written']} repo targets + Hermes.app updated."
    )
    return 0


def run_tui(refresh_dock: bool = False) -> int:
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print("Interactive TUI requires a terminal (TTY). Try 'hermes-icon list' or 'hermes-icon gui'.", file=sys.stderr)
        return 1

    cfg = load_config()
    selected_idx = PRESET_ORDER.index(cfg.preset) if cfg.mode == "preset" and cfg.preset in PRESET_ORDER else 0
    preview_cache: dict[str, list[str]] = {}
    last_term_cols = shutil.get_terminal_size((100, 30)).columns
    status_msg = ""

    def draw() -> None:
        nonlocal last_term_cols
        cur_cols = shutil.get_terminal_size((100, 30)).columns
        if (cur_cols >= 116) != (last_term_cols >= 116):
            preview_cache.clear()
        last_term_cols = cur_cols
        frame = render_tui_frame(
            cfg,
            selected_idx,
            preview_cache,
            status_msg=status_msg,
            term_cols=cur_cols,
        )
        sys.stdout.write(frame)
        sys.stdout.flush()

    fd = sys.stdin.fileno()
    old_tty = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        while True:
            termios.tcsetattr(fd, termios.TCSANOW, old_tty)
            draw()
            tty.setraw(fd)
            key = _read_key(fd)
            if key in ("q", "Q", "ESC", "QUIT"):
                termios.tcsetattr(fd, termios.TCSANOW, old_tty)
                sys.stdout.write("\n")
                return 0
            if key in ("UP", "k", "K"):
                selected_idx = (selected_idx - 1) % len(PRESET_ORDER)
                status_msg = ""
            elif key in ("DOWN", "j", "J"):
                selected_idx = (selected_idx + 1) % len(PRESET_ORDER)
                status_msg = ""
            elif key in tuple(str(n) for n in range(1, len(PRESET_ORDER) + 1)):
                selected_idx = int(key) - 1
                status_msg = ""
            elif key in ("g", "G"):
                termios.tcsetattr(fd, termios.TCSANOW, old_tty)
                sys.stdout.write("\n")
                from .gui import run_gui
                return run_gui()
            elif key == "ENTER":
                termios.tcsetattr(fd, termios.TCSANOW, old_tty)
                chosen = PRESET_ORDER[selected_idx]
                new_cfg = IconConfig(
                    mode="preset",
                    preset=chosen,
                    bg_light=cfg.bg_light,
                    bg_dark=cfg.bg_dark,
                    fg_light=cfg.fg_light,
                    fg_dark=cfg.fg_dark,
                    scale=cfg.scale,
                )
                return _apply_with_progress(new_cfg, chosen, refresh_dock)
            elif key in ("f", "F"):
                termios.tcsetattr(fd, termios.TCSANOW, old_tty)
                chosen_file = _pick_file_via_finder()
                if chosen_file:
                    new_cfg = IconConfig(
                        mode="custom",
                        custom_path=chosen_file,
                        bg_light=cfg.bg_light,
                        bg_dark=cfg.bg_dark,
                        fg_light=cfg.fg_light,
                        fg_dark=cfg.fg_dark,
                        scale=cfg.scale,
                    )
                    return _apply_with_progress(new_cfg, chosen_file, refresh_dock)
                status_msg = "Finder file selection cancelled."
                tty.setraw(fd)
            elif key in ("c", "C"):
                termios.tcsetattr(fd, termios.TCSANOW, old_tty)
                sys.stdout.write("\nEnter custom icon path (.svg/.png/.icns/.jpg/.webp): ")
                sys.stdout.flush()
                entered = sys.stdin.readline().strip().strip("'\"")
                if entered:
                    p = Path(entered).expanduser()
                    if not p.exists():
                        status_msg = f"File not found: {p}"
                        tty.setraw(fd)
                        continue
                    new_cfg = IconConfig(
                        mode="custom",
                        custom_path=str(p),
                        bg_light=cfg.bg_light,
                        bg_dark=cfg.bg_dark,
                        fg_light=cfg.fg_light,
                        fg_dark=cfg.fg_dark,
                        scale=cfg.scale,
                    )
                    return _apply_with_progress(new_cfg, str(p), refresh_dock)
                status_msg = "No path entered."
                tty.setraw(fd)
    finally:
        termios.tcsetattr(fd, termios.TCSANOW, old_tty)
