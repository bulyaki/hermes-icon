"""Orchestrator for applying icons across all Hermes surfaces and verifying state."""

from __future__ import annotations

import contextlib
import errno
import fcntl
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .asar import patch_asar, read_asar_header, verify_asar_integrity
from .backup import ensure_original_backup, load_backup_manifest, sha256_file
from .config import (
    APPLICATIONS_HERMES_APP,
    CUSTOM_ASSETS_DIR,
    ENTITLEMENTS_PLIST,
    HERMES_APP,
    HERMES_REPO,
    HERMES_UPDATE_LOCK,
    HERMES_UPDATE_MARKER,
    LOGS_DIR,
    REPLACER_LOCK_PATH,
    IconConfig,
    ensure_dirs,
    load_config,
    load_state,
    save_config,
    save_state,
)

ACTIVE_LOCK_WINDOW_SECONDS = 300
WATCHER_COOLDOWN_SECONDS = 10.0
ACTOOL_TIMEOUT_SECONDS = 20.0


class LockBusyError(RuntimeError):
    """Raised when replacer.lock is held and non-blocking mode was requested."""


def _log_watcher_warning(msg: str) -> None:
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        with (LOGS_DIR / "watcher.err.log").open("a", encoding="utf-8") as fh:
            fh.write(f"[{datetime.now(timezone.utc).isoformat()}] {msg}\n")
    except OSError:
        pass


def _read_lock_holder(lock_path: Path) -> dict[str, Any] | None:
    try:
        raw = lock_path.read_text(encoding="utf-8").strip()
        if not raw:
            return None
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _terminate_pid_tree(pid: int) -> None:
    if pid <= 1 or pid == os.getpid():
        return
    try:
        os.kill(pid, 0)
    except OSError:
        return

    # Terminate any children (such as actool / ibtoold) first, then the holder
    for sig_name, sig in (("TERM", signal.SIGTERM), ("KILL", signal.SIGKILL)):
        try:
            subprocess.run(
                ["/usr/bin/pkill", f"-{sig_name}", "-P", str(pid)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=2,
            )
        except Exception:
            pass
        try:
            os.kill(pid, sig)
        except OSError:
            return
        deadline = time.monotonic() + (0.45 if sig == signal.SIGTERM else 0.25)
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except OSError:
                return
            time.sleep(0.05)


@contextlib.contextmanager
def replacer_lock(
    lock_path: Path = REPLACER_LOCK_PATH,
    *,
    blocking: bool = True,
    mode: str = "interactive",
    preempt_watcher: bool = True,
    timeout: float = 15.0,
):
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
    acquired = False
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except OSError as exc:
            if exc.errno not in (errno.EAGAIN, errno.EACCES, errno.EWOULDBLOCK):
                raise
            if not blocking:
                raise LockBusyError("replacer.lock is busy") from exc

            if preempt_watcher:
                holder = _read_lock_holder(lock_path)
                if holder:
                    h_pid = int(holder.get("pid") or 0)
                    h_mode = holder.get("mode")
                    h_ts = float(holder.get("ts") or 0.0)
                    if h_pid and h_pid != os.getpid() and (
                        h_mode == "watcher" or (h_ts > 0 and time.time() - h_ts > 10.0)
                    ):
                        _terminate_pid_tree(h_pid)

            deadline = time.monotonic() + timeout
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                    break
                except OSError as exc2:
                    if exc2.errno not in (errno.EAGAIN, errno.EACCES, errno.EWOULDBLOCK):
                        raise
                    if time.monotonic() >= deadline:
                        raise LockBusyError("Timed out waiting for replacer.lock") from exc2
                    time.sleep(0.05)

        meta = json.dumps({"pid": os.getpid(), "mode": mode, "ts": time.time()}).encode("utf-8")
        os.ftruncate(fd, 0)
        os.lseek(fd, 0, os.SEEK_SET)
        os.write(fd, meta)
        yield
    finally:
        if acquired:
            try:
                os.ftruncate(fd, 0)
            except OSError:
                pass
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
        os.close(fd)


def is_update_in_progress() -> tuple[bool, str | None]:
    """Return ``(True, reason)`` if a Hermes update or Electron build is actively running."""
    now = time.time()
    for lock_file in (HERMES_UPDATE_LOCK, HERMES_UPDATE_MARKER):
        if lock_file.exists():
            try:
                age = now - lock_file.stat().st_mtime
                if age < ACTIVE_LOCK_WINDOW_SECONDS:
                    return True, f"Recent update lock {lock_file.name} (age {int(age)}s)"
            except OSError:
                pass

    for pattern in (r"hermes(\s+|-cli\s+)update", r"electron-builder", r"/usr/bin/actool"):
        try:
            res = subprocess.run(
                ["/usr/bin/pgrep", "-f", pattern],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=2,
            )
            if res.returncode == 0 and res.stdout.strip():
                pids = [
                    p.strip()
                    for p in res.stdout.strip().splitlines()
                    if p.strip() and int(p.strip()) != os.getpid()
                ]
                if pids:
                    return True, f"Active process matching {pattern!r} (pid={','.join(pids)})"
        except Exception:
            pass

    return False, None


def _wait_for_app_stability(hermes_app: Path, timeout: float = 5.0) -> None:
    """Wait briefly until Hermes.app Info.plist and app.asar are readable and stable."""
    plist_p = hermes_app / "Contents" / "Info.plist"
    asar_p = hermes_app / "Contents" / "Resources" / "app.asar"
    if not (plist_p.exists() and asar_p.exists()):
        return
    deadline = time.monotonic() + timeout
    prev: tuple[int, int, int, int] | None = None
    while time.monotonic() < deadline:
        try:
            s1 = plist_p.stat()
            s2 = asar_p.stat()
            sig = (s1.st_size, s1.st_mtime_ns, s2.st_size, s2.st_mtime_ns)
            if prev == sig:
                return
            prev = sig
        except OSError:
            pass
        time.sleep(0.2)


def _tracked_surface_paths(
    repo: Path = HERMES_REPO,
    hermes_app: Path = HERMES_APP,
    applications_app: Path = APPLICATIONS_HERMES_APP,
) -> dict[str, Path]:
    surfaces: dict[str, Path] = {
        "repo/assets/nous-girl-black.svg": repo / "assets" / "nous-girl-black.svg",
        "repo/assets/nous-girl-white.svg": repo / "assets" / "nous-girl-white.svg",
        "repo/apps/desktop/assets/icon.icns": repo / "apps" / "desktop" / "assets" / "icon.icns",
        "repo/apps/desktop/assets/icon-mac.png": repo / "apps" / "desktop" / "assets" / "icon-mac.png",
        "repo/apps/desktop/public/nous-girl.png": repo / "apps" / "desktop" / "public" / "nous-girl.png",
        "repo/apps/desktop/public/nous-girl-dark.png": repo / "apps" / "desktop" / "public" / "nous-girl-dark.png",
        "repo/apps/desktop/public/apple-touch-icon.png": repo / "apps" / "desktop" / "public" / "apple-touch-icon.png",
        "repo/hermes_cli/web_dist/favicon.ico": repo / "hermes_cli" / "web_dist" / "favicon.ico",
    }
    if hermes_app.exists():
        surfaces.update(
            {
                "hermes_app/Contents/Resources/icon.icns": hermes_app / "Contents" / "Resources" / "icon.icns",
                "hermes_app/Contents/Resources/icon.ico": hermes_app / "Contents" / "Resources" / "icon.ico",
                "hermes_app/Contents/Resources/app.asar": hermes_app / "Contents" / "Resources" / "app.asar",
                "hermes_app/Contents/Resources/app.asar.unpacked/dist/apple-touch-icon.png": (
                    hermes_app / "Contents" / "Resources" / "app.asar.unpacked" / "dist" / "apple-touch-icon.png"
                ),
                "hermes_app/Contents/Resources/app.asar.unpacked/dist/nous-girl.png": (
                    hermes_app / "Contents" / "Resources" / "app.asar.unpacked" / "dist" / "nous-girl.png"
                ),
                "hermes_app/Contents/Resources/app.asar.unpacked/dist/nous-girl-dark.png": (
                    hermes_app / "Contents" / "Resources" / "app.asar.unpacked" / "dist" / "nous-girl-dark.png"
                ),
                "hermes_app/Contents/Info.plist": hermes_app / "Contents" / "Info.plist",
            }
        )
        assets_car = hermes_app / "Contents" / "Resources" / "Assets.car"
        if assets_car.exists():
            surfaces["hermes_app/Contents/Resources/Assets.car"] = assets_car
    if applications_app.exists():
        icns = applications_app / "Contents" / "Resources" / "icon.icns"
        if icns.exists() and os.access(icns, os.W_OK):
            surfaces["applications_hermes_app/Contents/Resources/icon.icns"] = icns
    return surfaces


def compute_surface_hashes(
    repo: Path = HERMES_REPO,
    hermes_app: Path = HERMES_APP,
    applications_app: Path = APPLICATIONS_HERMES_APP,
) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, path in _tracked_surface_paths(repo, hermes_app, applications_app).items():
        if path.exists():
            out[key] = sha256_file(path)
    return out


def _compile_assets_car(icon_icon_dir: Path, out_assets_car: Path) -> bool:
    """Compile Icon Composer package to Assets.car without pipe inheritance hangs."""
    with tempfile.TemporaryDirectory(prefix="hermes-actool-") as tmp:
        tmp_path = Path(tmp)
        partial_plist = tmp_path / "partial.plist"
        log_path = tmp_path / "actool.log"
        compiled = tmp_path / "Assets.car"
        cmd = [
            "/usr/bin/actool",
            "--compile",
            str(tmp_path),
            "--platform",
            "macosx",
            "--minimum-deployment-target",
            "13.0",
            "--app-icon",
            "icon",
            "--output-partial-info-plist",
            str(partial_plist),
            str(icon_icon_dir),
        ]
        with log_path.open("wb") as log_f:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=log_f,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            timed_out = False
            try:
                proc.wait(timeout=ACTOOL_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                timed_out = True
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except OSError:
                    pass
                proc.wait()

        if compiled.exists() and compiled.stat().st_size > 0 and (not timed_out or proc.returncode == 0):
            tmp_dst = out_assets_car.with_suffix(".car.tmp")
            shutil.copy2(compiled, tmp_dst)
            os.replace(tmp_dst, out_assets_car)
            return True

        if timed_out and compiled.exists() and compiled.stat().st_size > 0:
            tmp_dst = out_assets_car.with_suffix(".car.tmp")
            shutil.copy2(compiled, tmp_dst)
            os.replace(tmp_dst, out_assets_car)
            return True

        log_tail = ""
        try:
            log_tail = log_path.read_text(encoding="utf-8", errors="replace").strip()[-400:]
        except OSError:
            pass
        warn = (
            f"Warning: actool {'timed out after 12s' if timed_out else f'failed (rc={proc.returncode})'}; "
            f"keeping icon.icns fallback. {log_tail}"
        )
        _log_watcher_warning(warn)
        print(warn, file=sys.stderr)
        # Never leave a stale Assets.car (which would keep showing the old nous-girl icon)
        if out_assets_car.exists():
            try:
                out_assets_car.unlink()
            except OSError:
                pass
        return False


def _collect_asar_replacements(repo: Path, asar_path: Path) -> dict[str, bytes]:
    tree, _, _ = read_asar_header(asar_path)
    desktop_dir = repo / "apps" / "desktop"
    replacements: dict[str, bytes] = {}

    def walk(node: dict[str, Any], prefix: str = "") -> None:
        for name, entry in node.get("files", {}).items():
            rel = f"{prefix}/{name}" if prefix else name
            if "files" in entry:
                walk(entry, rel)
                continue
            if rel.startswith("assets/"):
                candidate = desktop_dir / rel
                if candidate.is_file():
                    replacements[rel] = candidate.read_bytes()
            elif rel in (
                "public/apple-touch-icon.png",
                "public/nous-girl.png",
                "public/nous-girl-dark.png",
            ):
                candidate = desktop_dir / rel
                if candidate.is_file():
                    replacements[rel] = candidate.read_bytes()
            elif rel in (
                "dist/apple-touch-icon.png",
                "dist/nous-girl.png",
                "dist/nous-girl-dark.png",
            ):
                candidate = desktop_dir / "public" / Path(rel).name
                if candidate.is_file():
                    replacements[rel] = candidate.read_bytes()

    walk(tree)
    return replacements


def _codesign_hermes_app(hermes_app: Path, entitlements: Path = ENTITLEMENTS_PLIST) -> None:
    cmd = ["/usr/bin/codesign", "--force", "--sign", "-", "--options", "runtime"]
    if entitlements.exists():
        cmd.extend(["--entitlements", str(entitlements)])
    cmd.append(str(hermes_app))
    proc = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"codesign failed (rc={proc.returncode}): {proc.stderr}")

    verify = subprocess.run(
        ["/usr/bin/codesign", "--verify", "--strict", str(hermes_app)],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
    )
    if verify.returncode != 0:
        raise RuntimeError(f"codesign --verify --strict failed: {verify.stderr}")


def refresh_macos_icon_cache(
    paths: list[Path],
    *,
    refresh_dock: bool = False,
) -> None:
    """Notify macOS Workspace/Finder that app bundle icons changed."""
    existing = [p for p in paths if p.exists()]
    for p in existing:
        try:
            os.utime(p, None)
        except OSError:
            pass

    if existing:
        js_lines = ['ObjC.import("AppKit");', "var ws = $.NSWorkspace.sharedWorkspace;"]
        for p in existing:
            escaped = str(p).replace("\\", "\\\\").replace('"', '\\"')
            js_lines.append(f'ws.noteFileSystemChanged("{escaped}");')
        try:
            subprocess.run(
                ["/usr/bin/osascript", "-l", "JavaScript", "-e", "\n".join(js_lines)],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except Exception:
            pass

    if refresh_dock:
        for proc_name in ("Dock", "Finder"):
            try:
                subprocess.run(
                    ["/usr/bin/killall", proc_name],
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    timeout=3,
                )
            except Exception:
                pass


def _cache_custom_files(cfg: IconConfig) -> IconConfig:
    """Keep resilient fallback copies of custom icons inside custom-cache/."""
    if cfg.mode != "custom" or not cfg.custom_path:
        return cfg
    CUSTOM_ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    src = Path(cfg.custom_path)
    if src.exists() and src.parent.resolve() != CUSTOM_ASSETS_DIR.resolve():
        cached = CUSTOM_ASSETS_DIR / f"custom_light{src.suffix.lower()}"
        shutil.copy2(src, cached)
        cfg.extra["cached_custom_path"] = str(cached)
    elif not src.exists() and cfg.extra.get("cached_custom_path"):
        cached = Path(cfg.extra["cached_custom_path"])
        if cached.exists():
            cfg.custom_path = str(cached)

    if cfg.custom_dark_path:
        dsrc = Path(cfg.custom_dark_path)
        if dsrc.exists() and dsrc.parent.resolve() != CUSTOM_ASSETS_DIR.resolve():
            dcached = CUSTOM_ASSETS_DIR / f"custom_dark{dsrc.suffix.lower()}"
            shutil.copy2(dsrc, dcached)
            cfg.extra["cached_custom_dark_path"] = str(dcached)
        elif not dsrc.exists() and cfg.extra.get("cached_custom_dark_path"):
            dcached = Path(cfg.extra["cached_custom_dark_path"])
            if dcached.exists():
                cfg.custom_dark_path = str(dcached)
    return cfg


def _apply_icon_locked(
    cfg: IconConfig,
    *,
    repo: Path = HERMES_REPO,
    hermes_app: Path = HERMES_APP,
    applications_app: Path = APPLICATIONS_HERMES_APP,
    save_active_config: bool = True,
    refresh_dock: bool = False,
    run_upstream_generator: bool = False,
    run_upstream_check: bool = False,
    progress_cb: Callable[[int, int, str], None] | None = None,
) -> dict[str, Any]:
    def emit(step: int, total: int, msg: str) -> None:
        if progress_cb is not None:
            progress_cb(step, total, msg)

    # Always back up original files before first modification
    ensure_original_backup(repo=repo, hermes_app=hermes_app, applications_app=applications_app)
    cfg = _cache_custom_files(cfg)

    # 1. Repo & 99 generated targets
    emit(1, 4, "Rendering icon targets...")
    from .renderer import apply_to_repo

    repo_res = apply_to_repo(
        cfg,
        repo=repo,
        run_upstream_generator=run_upstream_generator,
        run_upstream_check=run_upstream_check,
    )

    # Web UI favicon
    src_favicon = repo / "web" / "public" / "favicon.ico"
    dst_favicon = repo / "hermes_cli" / "web_dist" / "favicon.ico"
    if src_favicon.exists() and dst_favicon.parent.exists():
        shutil.copy2(src_favicon, dst_favicon)

    # 2-4. Packaged Desktop App (Hermes.app)
    app_res: dict[str, Any] = {"patched": False}
    if hermes_app.exists():
        _wait_for_app_stability(hermes_app)
        res_dir = hermes_app / "Contents" / "Resources"
        info_plist = hermes_app / "Contents" / "Info.plist"
        desktop_assets = repo / "apps" / "desktop" / "assets"
        desktop_public = repo / "apps" / "desktop" / "public"

        emit(2, 4, "Compiling macOS 26 Assets.car...")
        assets_car_compiled = _compile_assets_car(desktop_assets / "icon.icon", res_dir / "Assets.car")

        emit(3, 4, "Patching Hermes.app & app.asar...")
        shutil.copy2(desktop_assets / "icon.icns", res_dir / "icon.icns")
        shutil.copy2(desktop_assets / "icon.ico", res_dir / "icon.ico")

        unpacked_dist = res_dir / "app.asar.unpacked" / "dist"
        if unpacked_dist.exists():
            for fname in ("apple-touch-icon.png", "nous-girl.png", "nous-girl-dark.png"):
                shutil.copy2(desktop_public / fname, unpacked_dist / fname)

        asar_path = res_dir / "app.asar"
        replacements = _collect_asar_replacements(repo, asar_path)
        asar_res = patch_asar(asar_path, replacements, info_plist_path=info_plist)

        ok, errs = verify_asar_integrity(
            asar_path,
            info_plist,
            unpacked_dir=res_dir / "app.asar.unpacked",
            check_paths=list(replacements.keys()),
        )
        if not ok:
            raise RuntimeError(f"ASAR verification failed after patching: {errs}")

        emit(4, 4, "Re-signing & refreshing icon cache...")
        _codesign_hermes_app(hermes_app)
        app_res = {
            "patched": True,
            "assets_car_compiled": assets_car_compiled,
            "asar": asar_res,
            "codesign_verified": True,
        }
    else:
        emit(4, 4, "Refreshing icon cache...")

    # /Applications/Hermes.app/Contents/Resources/icon.icns if present & writable
    apps_patched = False
    apps_icns = applications_app / "Contents" / "Resources" / "icon.icns"
    if apps_icns.exists() and os.access(apps_icns, os.W_OK):
        shutil.copy2(repo / "apps" / "desktop" / "assets" / "icon.icns", apps_icns)
        apps_patched = True

    refresh_paths = [hermes_app]
    if apps_patched:
        refresh_paths.append(applications_app)
    refresh_macos_icon_cache(refresh_paths, refresh_dock=refresh_dock)

    if save_active_config:
        cfg.watch_paused = False
        save_config(cfg)

    hashes = compute_surface_hashes(repo, hermes_app, applications_app)
    save_state(
        {
            "applied_at": datetime.now(timezone.utc).isoformat(),
            "mode": cfg.mode,
            "preset": cfg.preset if cfg.mode == "preset" else None,
            "custom_path": cfg.custom_path if cfg.mode == "custom" else None,
            "hashes": hashes,
        }
    )

    return {
        "repo": repo_res,
        "hermes_app": app_res,
        "applications_hermes_app_patched": apps_patched,
        "surfaces_tracked": len(hashes),
    }


def apply_icon(
    cfg: IconConfig,
    *,
    repo: Path = HERMES_REPO,
    hermes_app: Path = HERMES_APP,
    applications_app: Path = APPLICATIONS_HERMES_APP,
    save_active_config: bool = True,
    refresh_dock: bool = False,
    run_upstream_generator: bool = False,
    run_upstream_check: bool = False,
    progress_cb: Callable[[int, int, str], None] | None = None,
) -> dict[str, Any]:
    """Apply ``cfg`` across repo, web_dist, Hermes.app, and /Applications/Hermes.app."""
    ensure_dirs()
    with replacer_lock(blocking=True, mode="interactive", preempt_watcher=True):
        return _apply_icon_locked(
            cfg,
            repo=repo,
            hermes_app=hermes_app,
            applications_app=applications_app,
            save_active_config=save_active_config,
            refresh_dock=refresh_dock,
            run_upstream_generator=run_upstream_generator,
            run_upstream_check=run_upstream_check,
            progress_cb=progress_cb,
        )


def inspect_surfaces(
    repo: Path = HERMES_REPO,
    hermes_app: Path = HERMES_APP,
    applications_app: Path = APPLICATIONS_HERMES_APP,
) -> dict[str, Any]:
    """Fast (<20ms) surface check comparing live SHA-256 hashes against state & backup manifest."""
    state = load_state()
    expected: dict[str, str] = state.get("hashes", {})
    backup = load_backup_manifest() or {}
    original_files: dict[str, Any] = backup.get("files", {})

    surfaces = _tracked_surface_paths(repo, hermes_app, applications_app)
    drifted: list[dict[str, str]] = []
    restored_to_original: list[str] = []
    missing: list[str] = []
    ok_count = 0

    for key, path in surfaces.items():
        if not path.exists():
            missing.append(key)
            continue
        cur_hash = sha256_file(path)
        orig_hash = original_files.get(key, {}).get("sha256")
        exp_hash = expected.get(key)
        if orig_hash and cur_hash == orig_hash:
            restored_to_original.append(key)
        if exp_hash and cur_hash != exp_hash:
            drifted.append({"surface": key, "expected": exp_hash, "actual": cur_hash})
        elif exp_hash and cur_hash == exp_hash:
            ok_count += 1

    needs_apply = bool(drifted or restored_to_original or not expected)
    return {
        "has_state": bool(expected),
        "total_surfaces": len(surfaces),
        "matching": ok_count,
        "drifted": drifted,
        "restored_to_original": restored_to_original,
        "missing": missing,
        "needs_apply": needs_apply,
        "backup_present": bool(backup),
    }


def _within_apply_cooldown() -> bool:
    applied_at = load_state().get("applied_at")
    if not applied_at:
        return False
    try:
        dt = datetime.fromisoformat(str(applied_at))
        age = (datetime.now(timezone.utc) - dt).total_seconds()
        return 0.0 <= age < WATCHER_COOLDOWN_SECONDS
    except Exception:
        return False


def check_and_heal(
    *,
    apply_if_needed: bool = False,
    delay: float = 0.0,
    repo: Path = HERMES_REPO,
    hermes_app: Path = HERMES_APP,
    applications_app: Path = APPLICATIONS_HERMES_APP,
) -> dict[str, Any]:
    """Check whether any surface reverted; if ``apply_if_needed``, safely re-apply active config."""
    if delay > 0:
        time.sleep(delay)

    cfg = load_config()
    if not apply_if_needed:
        report = inspect_surfaces(repo, hermes_app, applications_app)
        report["watch_paused"] = cfg.watch_paused
        report["action"] = "none"
        return report

    if cfg.watch_paused:
        report = inspect_surfaces(repo, hermes_app, applications_app)
        report["watch_paused"] = True
        report["action"] = "skipped_paused"
        return report

    if _within_apply_cooldown():
        return {
            "has_state": True,
            "total_surfaces": 0,
            "matching": 0,
            "drifted": [],
            "restored_to_original": [],
            "missing": [],
            "needs_apply": False,
            "backup_present": True,
            "watch_paused": False,
            "action": "skipped_cooldown",
        }

    try:
        with replacer_lock(blocking=False, mode="watcher", preempt_watcher=False):
            report = inspect_surfaces(repo, hermes_app, applications_app)
            report["watch_paused"] = cfg.watch_paused
            report["action"] = "none"

            if not report["needs_apply"]:
                report["action"] = "up_to_date"
                return report

            busy, reason = is_update_in_progress()
            if busy:
                report["action"] = "deferred_update_in_progress"
                report["reason"] = reason
                return report

            apply_res = _apply_icon_locked(
                cfg,
                repo=repo,
                hermes_app=hermes_app,
                applications_app=applications_app,
                save_active_config=False,
            )
            report["action"] = "reapplied"
            report["apply_result"] = apply_res
            return report
    except LockBusyError:
        return {
            "has_state": True,
            "total_surfaces": 0,
            "matching": 0,
            "drifted": [],
            "restored_to_original": [],
            "missing": [],
            "needs_apply": False,
            "backup_present": True,
            "watch_paused": cfg.watch_paused,
            "action": "skipped_locked",
        }
