"""Original nous-girl icon backup and restore logic."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .asar import patch_asar
from .config import (
    APPLICATIONS_HERMES_APP,
    BACKUPS_MANIFEST,
    BACKUPS_ORIGINAL_DIR,
    ENTITLEMENTS_PLIST,
    GENERATE_ICONS_PY,
    HERMES_APP,
    HERMES_REPO,
    WEB_DIST_FAVICON,
    discover_windows_app_dirs,
    msix_assets_dir_for_win_app,
    windows_app_surface_labels,
)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(1048576)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _backup_targets(
    repo: Path = HERMES_REPO,
    hermes_app: Path = HERMES_APP,
    applications_app: Path = APPLICATIONS_HERMES_APP,
    win_app_dirs: list[Path] | None = None,
) -> list[tuple[str, Path]]:
    """Return ``(backup_relpath, live_path)`` pairs to preserve on first run."""
    items: list[tuple[str, Path]] = [
        ("repo/assets/nous-girl-black.svg", repo / "assets" / "nous-girl-black.svg"),
        ("repo/assets/nous-girl-white.svg", repo / "assets" / "nous-girl-white.svg"),
        ("repo/apps/desktop/assets/icon.icns", repo / "apps" / "desktop" / "assets" / "icon.icns"),
        ("repo/apps/desktop/assets/icon-mac.png", repo / "apps" / "desktop" / "assets" / "icon-mac.png"),
        ("repo/apps/desktop/public/nous-girl.png", repo / "apps" / "desktop" / "public" / "nous-girl.png"),
        ("repo/apps/desktop/public/nous-girl-dark.png", repo / "apps" / "desktop" / "public" / "nous-girl-dark.png"),
        ("repo/apps/desktop/public/apple-touch-icon.png", repo / "apps" / "desktop" / "public" / "apple-touch-icon.png"),
        ("repo/hermes_cli/web_dist/favicon.ico", repo / "hermes_cli" / "web_dist" / "favicon.ico"),
        ("hermes_app/Contents/Resources/icon.icns", hermes_app / "Contents" / "Resources" / "icon.icns"),
        ("hermes_app/Contents/Resources/Assets.car", hermes_app / "Contents" / "Resources" / "Assets.car"),
        ("hermes_app/Contents/Resources/icon.ico", hermes_app / "Contents" / "Resources" / "icon.ico"),
        ("hermes_app/Contents/Info.plist", hermes_app / "Contents" / "Info.plist"),
        (
            "hermes_app/Contents/Resources/app.asar.unpacked/dist/apple-touch-icon.png",
            hermes_app / "Contents" / "Resources" / "app.asar.unpacked" / "dist" / "apple-touch-icon.png",
        ),
        (
            "hermes_app/Contents/Resources/app.asar.unpacked/dist/nous-girl.png",
            hermes_app / "Contents" / "Resources" / "app.asar.unpacked" / "dist" / "nous-girl.png",
        ),
        (
            "hermes_app/Contents/Resources/app.asar.unpacked/dist/nous-girl-dark.png",
            hermes_app / "Contents" / "Resources" / "app.asar.unpacked" / "dist" / "nous-girl-dark.png",
        ),
        ("hermes_app/Contents/Resources/app.asar", hermes_app / "Contents" / "Resources" / "app.asar"),
    ]
    if applications_app.exists():
        app_icns = applications_app / "Contents" / "Resources" / "icon.icns"
        if app_icns.exists():
            items.append(("applications_hermes_app/Contents/Resources/icon.icns", app_icns))
    resolved_win_dirs = win_app_dirs if win_app_dirs is not None else discover_windows_app_dirs(repo)
    win_labels = windows_app_surface_labels(resolved_win_dirs)

    for wdir in resolved_win_dirs:
        wres = wdir / "resources"
        label = win_labels[wdir]
        prefix = f"win_app/{label}/resources"
        for sub, p in (
            ("icon.ico", wres / "icon.ico"),
            ("app.asar", wres / "app.asar"),
            ("app.asar.unpacked/dist/apple-touch-icon.png", wres / "app.asar.unpacked" / "dist" / "apple-touch-icon.png"),
            ("app.asar.unpacked/dist/nous-girl.png", wres / "app.asar.unpacked" / "dist" / "nous-girl.png"),
            ("app.asar.unpacked/dist/nous-girl-dark.png", wres / "app.asar.unpacked" / "dist" / "nous-girl-dark.png"),
        ):
            if p.exists():
                items.append((f"{prefix}/{sub}", p))
        msix_assets = msix_assets_dir_for_win_app(wdir)
        if msix_assets is not None:
            for tile_p in sorted(msix_assets.glob("*.png")):
                items.append((f"win_app/{label}/msix_assets/{tile_p.name}", tile_p))
    return items


def ensure_original_backup(
    backup_dir: Path = BACKUPS_ORIGINAL_DIR,
    repo: Path = HERMES_REPO,
    hermes_app: Path = HERMES_APP,
    applications_app: Path = APPLICATIONS_HERMES_APP,
    win_app_dirs: list[Path] | None = None,
) -> dict[str, Any]:
    """Create the original backup once and never overwrite an existing backup."""
    manifest_path = backup_dir / "manifest.json"
    if manifest_path.exists():
        return json.loads(manifest_path.read_text(encoding="utf-8"))

    backup_dir.mkdir(parents=True, exist_ok=True)
    files_meta: dict[str, dict[str, Any]] = {}
    for rel, src in _backup_targets(repo, hermes_app, applications_app, win_app_dirs=win_app_dirs):
        if not src.exists():
            continue
        dst = backup_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        files_meta[rel] = {
            "source_path": str(src),
            "sha256": sha256_file(dst),
            "size": dst.stat().st_size,
        }

    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "files": files_meta,
    }
    tmp = manifest_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, manifest_path)
    return manifest


def load_backup_manifest(backup_dir: Path = BACKUPS_ORIGINAL_DIR) -> dict[str, Any] | None:
    manifest_path = backup_dir / "manifest.json"
    if not manifest_path.exists():
        return None
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def restore_original_icons(
    backup_dir: Path = BACKUPS_ORIGINAL_DIR,
    repo: Path = HERMES_REPO,
    hermes_app: Path = HERMES_APP,
    applications_app: Path = APPLICATIONS_HERMES_APP,
) -> dict[str, Any]:
    """Restore original nous-girl icons across repo, Hermes.app, web_dist, and /Applications/Hermes.app."""
    manifest = load_backup_manifest(backup_dir)
    if manifest is None:
        raise FileNotFoundError(f"Original backup manifest not found at {backup_dir / 'manifest.json'}")

    restored: list[str] = []
    # 1. Restore nous-girl SVGs first and regenerate all 99 repo targets when a repo exists
    if (repo / "assets").is_dir():
        for rel in ("repo/assets/nous-girl-black.svg", "repo/assets/nous-girl-white.svg"):
            src = backup_dir / rel
            if src.exists():
                dst = repo / rel.removeprefix("repo/")
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                restored.append(str(dst))

        gen_py = repo / "scripts" / "generate_icons.py"
        if not gen_py.is_file() and repo == HERMES_REPO and GENERATE_ICONS_PY.is_file():
            gen_py = GENERATE_ICONS_PY
        if gen_py.is_file():
            env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME")}
            proc = subprocess.run(
                [sys.executable, "-I", str(gen_py), "--source", str(repo), "--out", str(repo)],
                capture_output=True,
                text=True,
                env=env,
            )
            if proc.returncode != 0:
                raise RuntimeError(f"generate_icons.py restore failed: {proc.stdout}\n{proc.stderr}")

    # 2. Restore exact backed-up files (web_dist, Hermes.app, /Applications/Hermes.app, Windows apps)
    win_dirs_to_relaunch: list[str] = []
    has_win_entries = any(k.startswith("win_app/") for k in manifest.get("files", {}))
    win_dirs: list[Path] = discover_windows_app_dirs(repo) if has_win_entries else []
    win_pairs_by_dir: dict[Path, list[tuple[Path, Path]]] = {}
    other_pairs: list[tuple[Path, Path]] = []

    for rel, meta in manifest.get("files", {}).items():
        if rel in ("repo/assets/nous-girl-black.svg", "repo/assets/nous-girl-white.svg"):
            continue
        src = backup_dir / rel
        if not src.exists():
            continue
        if rel.startswith("repo/"):
            dst = repo / rel.removeprefix("repo/")
        elif rel.startswith("hermes_app/"):
            dst = hermes_app / rel.removeprefix("hermes_app/")
        elif rel.startswith("applications_hermes_app/"):
            dst = applications_app / rel.removeprefix("applications_hermes_app/")
        else:
            dst = Path(meta["source_path"])
        if not dst.parent.exists():
            continue
        if rel.startswith("win_app/"):
            owner = next(
                (w for w in win_dirs if dst == w or w in dst.parents or (w.parent / "assets") in (dst, dst.parent)),
                win_dirs[0] if win_dirs else dst.parent,
            )
            win_pairs_by_dir.setdefault(owner, []).append((src, dst))
        else:
            other_pairs.append((src, dst))

    for src, dst in other_pairs:
        shutil.copy2(src, dst)
        restored.append(str(dst))

    if win_pairs_by_dir:
        from .applier import (
            _apply_windows_copy_pairs,
            _relaunch_windows_exes,
            _stop_windows_app_processes,
            refresh_windows_icon_cache,
        )

        try:
            for wdir, pairs in win_pairs_by_dir.items():
                if sys.platform == "win32":
                    win_dirs_to_relaunch.extend(_stop_windows_app_processes(wdir))
                _apply_windows_copy_pairs(wdir, pairs)
                restored.extend(str(dst) for _, dst in pairs)
        finally:
            if win_dirs_to_relaunch:
                _relaunch_windows_exes(win_dirs_to_relaunch)

        if sys.platform == "win32" and win_dirs:
            ico_p = win_dirs[0] / "resources" / "icon.ico"
            manifests = [
                mf
                for wdir in win_dirs
                for mf in (wdir / "AppxManifest.xml", wdir.parent / "AppxManifest.xml")
                if mf.exists()
            ]
            refresh_windows_icon_cache(ico_p, appx_manifest_paths=manifests)

    # Fallback if app.asar wasn't in backup for any reason: patch it from repo assets
    if "hermes_app/Contents/Resources/app.asar" not in manifest.get("files", {}) and hermes_app.exists():
        asar_path = hermes_app / "Contents" / "Resources" / "app.asar"
        info_plist = hermes_app / "Contents" / "Info.plist"
        if asar_path.exists():
            replacements = {}
            for sub_rel in (
                "public/apple-touch-icon.png",
                "public/nous-girl.png",
                "public/nous-girl-dark.png",
            ):
                p = repo / "apps" / "desktop" / sub_rel
                if p.exists():
                    replacements[sub_rel] = p.read_bytes()
            patch_asar(asar_path, replacements, info_plist_path=info_plist)

    # Re-sign Hermes.app on macOS if present
    if sys.platform == "darwin" and hermes_app.exists() and Path("/usr/bin/codesign").exists():
        cmd = [
            "/usr/bin/codesign",
            "--force",
            "--sign",
            "-",
            "--options",
            "runtime",
        ]
        if ENTITLEMENTS_PLIST.exists():
            cmd.extend(["--entitlements", str(ENTITLEMENTS_PLIST)])
        cmd.append(str(hermes_app))
        cs = subprocess.run(cmd, capture_output=True, text=True)
        if cs.returncode != 0:
            raise RuntimeError(f"codesign restore failed: {cs.stderr}")

    return {"restored_count": len(restored), "restored": restored}
