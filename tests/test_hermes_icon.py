"""Comprehensive test suite for hermes-icon."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import plistlib
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from datetime import datetime, timedelta, timezone
from PIL import Image, ImageDraw

from hermes_icon.applier import (
    apply_icon,
    check_and_heal,
    inspect_surfaces,
    is_update_in_progress,
    patch_windows_app_dir,
    replacer_lock,
)
from hermes_icon.asar import patch_asar, read_asar_header, verify_asar_integrity
from hermes_icon.backup import ensure_original_backup, load_backup_manifest, sha256_file
from hermes_icon.config import (
    APPLICATIONS_HERMES_APP,
    BACKUPS_ORIGINAL_DIR,
    GENERATE_ICONS_PY,
    HERMES_APP,
    HERMES_REPO,
    IconConfig,
    discover_windows_app_dirs,
    load_config,
    load_state,
    save_state,
)
from hermes_icon.gui import start_gui_server
from hermes_icon.presets import PRESET_ORDER, PRESETS, VIEWBOX, build_preset_svg, resolve_preset_id
from hermes_icon.renderer import IconRenderer, _load_generate_icons_module, apply_to_repo
from hermes_icon.tui import LEFT_COL_WIDTH, render_tui_frame
from hermes_icon.watcher import (
    WINDOWS_TASK_NAME,
    _launcher_bin,
    build_launchd_plist,
    build_windows_schtasks_create_cmd,
    build_windows_schtasks_delete_cmd,
    build_windows_schtasks_query_cmd,
    git_hooks_status,
    is_launchd_loaded,
)

BIN_HERMES_ICON = Path(__file__).resolve().parent.parent / "bin" / "hermes-icon"
BIN_HERMES_ICON_CMD = Path(__file__).resolve().parent.parent / "bin" / "hermes-icon.cmd"


class TestPresetsAndValidation(unittest.TestCase):
    def test_all_nine_presets_mlcz_grammar_and_render(self) -> None:
        self.assertEqual(len(PRESET_ORDER), 9)
        self.assertEqual(PRESET_ORDER[0], "disco-girl")
        self.assertEqual(resolve_preset_id("disco-nous"), "disco-girl")
        counts = {"M": 2, "L": 2, "C": 6, "Z": 0}
        gen_mod = _load_generate_icons_module()

        for pid in PRESET_ORDER:
            svg = build_preset_svg(pid, "#000000")
            self.assertIn(f'viewBox="0 0 {VIEWBOX} {VIEWBOX}"', svg)
            paths = re.findall(r"<path\b[^>]*/>", svg, re.DOTALL)
            self.assertEqual(len(paths), 1, f"{pid} must have exactly 1 <path>")
            d_match = re.search(r'd="([^"]+)"', paths[0])
            self.assertIsNotNone(d_match)
            d = d_match.group(1)

            tokens = re.findall(r"[A-Za-z]|[-+]?(?:\d*\.\d+|\d+\.?\d*)(?:[eE][-+]?\d+)?", d)
            idx = 0
            while idx < len(tokens):
                cmd = tokens[idx]
                self.assertIn(cmd, counts, f"{pid} contains disallowed SVG command {cmd!r}")
                c = counts[cmd]
                self.assertLess(idx + c, len(tokens), f"{pid} incomplete {cmd}")
                for k in range(1, c + 1):
                    float(tokens[idx + k])
                idx += c + 1

            # Verify generate_icons.drag_bottom_nodes accepts the path
            import xml.etree.ElementTree as ET
            el = ET.fromstring(paths[0])
            gen_mod.drag_bottom_nodes(el, cutoff=5000.0, band=100.0, distance=50.0)

            # Verify clean squircle rendering
            renderer = IconRenderer(IconConfig(mode="preset", preset=pid))
            sq_light = renderer.render_squircle(256, dark=False, mac_grid=False)
            sq_dark = renderer.render_squircle(256, dark=True, mac_grid=False)
            self.assertEqual(sq_light.size, (256, 256))
            self.assertEqual(sq_dark.size, (256, 256))
            self.assertEqual(sq_light.getchannel("A").getextrema(), (0, 255))
            self.assertEqual(sq_dark.getchannel("A").getextrema(), (0, 255))

        # Verify disco-girl bottom-anchors flush to the bottom edge and preserves chrome shading
        disco_sq = IconRenderer(IconConfig(mode="preset", preset="disco-girl")).render_squircle(
            256, dark=False, mac_grid=False
        )
        # Bottom center pixel inside squircle should be opaque portrait pixel (not pure white)
        r, g, b, a = disco_sq.getpixel((128, 254))
        self.assertEqual(a, 255)
        self.assertLess((r + g + b) / 3, 250)


class TestCustomIcons(unittest.TestCase):
    def _create_colored_png(self, path: Path) -> None:
        img = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.ellipse((64, 64, 448, 448), fill=(255, 90, 40, 255))
        draw.rectangle((180, 180, 332, 332), fill=(40, 180, 255, 255))
        img.save(path, "PNG")

    def _create_multicolor_svg(self, path: Path) -> None:
        path.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200">'
            '<circle cx="100" cy="100" r="80" fill="#10b981"/>'
            '<rect x="65" y="65" width="70" height="70" rx="14" fill="#f59e0b"/>'
            "</svg>\n",
            encoding="utf-8",
        )

    def _create_icns(self, path: Path) -> None:
        base = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
        draw = ImageDraw.Draw(base)
        draw.rounded_rectangle((100, 100, 924, 924), radius=185, fill=(75, 85, 220, 255))
        draw.ellipse((312, 312, 712, 712), fill=(255, 230, 80, 255))
        frames = [base.resize((s, s), Image.LANCZOS) for s in (16, 32, 64, 128, 256, 512, 1024)]
        base.save(path, format="ICNS", append_images=frames[1:])

    def _create_ico(self, path: Path) -> None:
        base = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
        draw = ImageDraw.Draw(base)
        draw.rounded_rectangle((24, 24, 232, 232), radius=48, fill=(220, 60, 100, 255))
        draw.ellipse((78, 78, 178, 178), fill=(80, 220, 190, 255))
        base.save(path, format="ICO", sizes=[(16, 16), (32, 32), (64, 64), (128, 128), (256, 256)])

    def test_custom_png_svg_icns_ico_preserve_color_and_pass_mlz(self) -> None:
        gen_mod = _load_generate_icons_module()
        import xml.etree.ElementTree as ET

        with tempfile.TemporaryDirectory(prefix="hermes-custom-test-") as tmp:
            tmp_dir = Path(tmp)
            png_p = tmp_dir / "logo.png"
            svg_p = tmp_dir / "logo.svg"
            icns_p = tmp_dir / "logo.icns"
            ico_p = tmp_dir / "logo.ico"
            self._create_colored_png(png_p)
            self._create_multicolor_svg(svg_p)
            self._create_icns(icns_p)
            self._create_ico(ico_p)

            for custom_file in (png_p, svg_p, icns_p, ico_p):
                cfg = IconConfig(mode="custom", custom_path=str(custom_file), scale=0.78)
                renderer = IconRenderer(cfg)
                sq = renderer.render_squircle(512, dark=False, mac_grid=False)
                self.assertEqual(sq.size, (512, 512))
                self.assertEqual(sq.getchannel("A").getextrema(), (0, 255))

                # Center pixel must preserve non-grayscale color from custom artwork
                r, g, b, a = sq.getpixel((256, 256))
                self.assertEqual(a, 255)
                self.assertFalse(r == g == b, f"{custom_file.name} lost color at center: {(r, g, b)}")

                # Source SVGs must be valid M/L/Z single-path SVGs
                black_svg, white_svg = renderer.source_svgs()
                for s_text in (black_svg, white_svg):
                    m = re.search(r"<path\b[^>]*/>", s_text, re.DOTALL)
                    self.assertIsNotNone(m)
                    el = ET.fromstring(m.group(0))
                    gen_mod.drag_bottom_nodes(el, cutoff=4000.0, band=100.0, distance=50.0)


class TestAsarPatching(unittest.TestCase):
    def test_asar_patch_and_integrity_roundtrip(self) -> None:
        asar_src = HERMES_APP / "Contents" / "Resources" / "app.asar"
        plist_src = HERMES_APP / "Contents" / "Info.plist"
        unpacked_src = HERMES_APP / "Contents" / "Resources" / "app.asar.unpacked"
        if not asar_src.exists():
            self.skipTest("Hermes.app app.asar not present")

        with tempfile.TemporaryDirectory(prefix="hermes-asar-test-") as tmp:
            tmp_dir = Path(tmp)
            asar_copy = tmp_dir / "app.asar"
            plist_copy = tmp_dir / "Info.plist"
            unpacked_copy = tmp_dir / "app.asar.unpacked"
            shutil.copy2(asar_src, asar_copy)
            shutil.copy2(plist_src, plist_copy)
            (unpacked_copy / "dist").mkdir(parents=True)

            fake_packed = b"\x89PNG\r\n\x1a\nFAKE_PACKED_ICON_" + os.urandom(256)
            fake_unpacked = b"\x89PNG\r\n\x1a\nFAKE_UNPACKED_ICON_" + os.urandom(128)
            (unpacked_copy / "dist" / "nous-girl.png").write_bytes(fake_unpacked)
            (unpacked_copy / "dist" / "nous-girl-dark.png").write_bytes(fake_unpacked)
            (unpacked_copy / "dist" / "apple-touch-icon.png").write_bytes(fake_unpacked)

            res = patch_asar(
                asar_copy,
                {
                    "public/nous-girl.png": fake_packed,
                    "assets/icon.png": fake_packed,
                    "dist/nous-girl.png": fake_unpacked,
                    "dist/nous-girl-dark.png": fake_unpacked,
                    "dist/apple-touch-icon.png": fake_unpacked,
                },
                info_plist_path=plist_copy,
            )
            self.assertGreaterEqual(res["packed_updated"], 2)
            self.assertEqual(res["unpacked_updated"], 3)

            ok, errs = verify_asar_integrity(
                asar_copy,
                plist_copy,
                unpacked_dir=unpacked_copy,
                check_paths=[
                    "public/nous-girl.png",
                    "assets/icon.png",
                    "dist/nous-girl.png",
                    "dist/nous-girl-dark.png",
                    "dist/apple-touch-icon.png",
                ],
            )
            self.assertTrue(ok, f"ASAR verify failed: {errs}")

            _, hdr_bytes, _ = read_asar_header(asar_copy)
            with plist_copy.open("rb") as f:
                plist_data = plistlib.load(f)
            self.assertEqual(
                hashlib.sha256(hdr_bytes).hexdigest(),
                plist_data["ElectronAsarIntegrity"]["Resources/app.asar"]["hash"],
            )

    def test_windows_unpacked_app_patch_and_asar_integrity(self) -> None:
        asar_src = HERMES_APP / "Contents" / "Resources" / "app.asar"
        if not asar_src.exists():
            self.skipTest("Hermes.app app.asar not present")

        with tempfile.TemporaryDirectory(prefix="hermes-win-test-") as tmp:
            tmp_dir = Path(tmp)
            fake_repo = tmp_dir / "hermes-agent"
            desktop_assets = fake_repo / "apps" / "desktop" / "assets"
            desktop_public = fake_repo / "apps" / "desktop" / "public"
            win_dir = fake_repo / "apps" / "desktop" / "release" / "win-unpacked"
            wres = win_dir / "resources"
            unpacked_dist = wres / "app.asar.unpacked" / "dist"

            desktop_assets.mkdir(parents=True)
            desktop_public.mkdir(parents=True)
            unpacked_dist.mkdir(parents=True)

            # Seed fake repo target icons matching expected Windows assets
            fake_ico = b"\x00\x00\x01\x00FAKE_WIN_ICO_" + os.urandom(64)
            fake_png = b"\x89PNG\r\n\x1a\nFAKE_WIN_PNG_" + os.urandom(64)
            (desktop_assets / "icon.ico").write_bytes(fake_ico)
            (desktop_assets / "icon.png").write_bytes(fake_png)
            (desktop_assets / "icon.icns").write_bytes(b"icns" + os.urandom(32))
            (desktop_assets / "icon-mac.png").write_bytes(fake_png)
            for fname in ("apple-touch-icon.png", "nous-girl.png", "nous-girl-dark.png"):
                (desktop_public / fname).write_bytes(fake_png)
                (unpacked_dist / fname).write_bytes(b"\x89PNG\r\n\x1a\nOLD_WIN_" + os.urandom(32))

            (wres / "icon.ico").write_bytes(b"OLD_ICO")
            shutil.copy2(asar_src, wres / "app.asar")

            discovered = discover_windows_app_dirs(fake_repo)
            self.assertIn(win_dir, discovered)

            res = patch_windows_app_dir(win_dir, fake_repo)
            self.assertTrue(res["patched"])
            self.assertEqual((wres / "icon.ico").read_bytes(), fake_ico)
            for fname in ("apple-touch-icon.png", "nous-girl.png", "nous-girl-dark.png"):
                self.assertEqual((unpacked_dist / fname).read_bytes(), fake_png)

            ok, errs = verify_asar_integrity(
                wres / "app.asar",
                None,
                unpacked_dir=wres / "app.asar.unpacked",
                check_paths=[
                    "public/nous-girl.png",
                    "assets/icon.png",
                    "dist/nous-girl.png",
                    "dist/nous-girl-dark.png",
                    "dist/apple-touch-icon.png",
                ],
            )
            self.assertTrue(ok, f"Windows ASAR verify failed: {errs}")


class TestGuiServer(unittest.TestCase):
    def test_gui_endpoints(self) -> None:
        server, url = start_gui_server(port=0, open_browser=False)
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        try:
            with urllib.request.urlopen(url) as r:
                self.assertEqual(r.status, 200)
                html = r.read().decode("utf-8")
                self.assertIn("Hermes Icon Picker", html)

            with urllib.request.urlopen(url + "api/status") as r:
                data = json.loads(r.read().decode("utf-8"))
                self.assertEqual(len(data["presets"]), 9)
                self.assertEqual(data["presets"][0]["id"], "disco-girl")

            with urllib.request.urlopen(url + "api/preview?mode=preset&preset=caduceus&appearance=light") as r:
                png = r.read()
                self.assertTrue(png.startswith(b"\x89PNG"))

            payload = json.dumps({
                "filename": "test.png",
                "data_base64": base64.b64encode(png).decode("ascii"),
            }).encode("utf-8")
            req = urllib.request.Request(
                url + "api/upload",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req) as r:
                up = json.loads(r.read().decode("utf-8"))
                self.assertIn("token", up)
        finally:
            server.shutdown()
            server.server_close()

    def test_gui_auto_exits_after_apply(self) -> None:
        orig_cfg = load_config()
        server, url = start_gui_server(port=0, open_browser=False, keep_open=False)
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        try:
            apply_payload = json.dumps({
                "mode": "preset",
                "preset": "caduceus",
                "bg_light": "#ffffff",
                "bg_dark": "#0d1117",
                "scale": 0.78,
                "full_bleed": False,
            }).encode("utf-8")
            req = urllib.request.Request(
                url + "api/apply",
                data=apply_payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req) as r:
                res = json.loads(r.read().decode("utf-8"))
                self.assertTrue(res["auto_quit"])
                self.assertIn("elapsed_s", res)
            t.join(timeout=3.0)
            self.assertFalse(t.is_alive(), "GUI server thread did not auto-shutdown after apply")
        finally:
            server.shutdown()
            server.server_close()
            apply_icon(orig_cfg)


class TestLockAndWatcherConfig(unittest.TestCase):
    def test_launchd_plist_standard_process_type(self) -> None:
        plist = build_launchd_plist()
        self.assertEqual(plist["ProcessType"], "Standard")
        self.assertIs(plist["LowPriorityIO"], False)
        self.assertEqual(plist["Nice"], 0)
        self.assertEqual(plist["ThrottleInterval"], 5)

    def test_version_flag_works_in_sandbox(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hermes-sandbox-home-") as tmp:
            env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": tmp}
            for flag in ("--version", "-V"):
                r = subprocess.run([str(BIN_HERMES_ICON), flag], capture_output=True, text=True, env=env)
                self.assertEqual(r.returncode, 0)
                self.assertEqual(r.stdout.strip(), "hermes-icon 0.1.2")

    def test_windows_task_scheduler_and_cmd_launcher(self) -> None:
        self.assertTrue(BIN_HERMES_ICON_CMD.is_file())
        cmd_text = BIN_HERMES_ICON_CMD.read_text(encoding="utf-8")
        self.assertIn("hermes-icon 0.1.2", cmd_text)
        self.assertIn("run.py", cmd_text)

        win_launcher = _launcher_bin(BIN_HERMES_ICON_CMD.parent, platform="win32")
        self.assertEqual(win_launcher, BIN_HERMES_ICON_CMD)

        create_cmd = build_windows_schtasks_create_cmd(win_launcher)
        self.assertEqual(create_cmd[:4], ["schtasks", "/Create", "/TN", WINDOWS_TASK_NAME])
        self.assertIn("MINUTE", create_cmd)
        self.assertIn(f'"{win_launcher}" check --apply', create_cmd)
        self.assertEqual(build_windows_schtasks_query_cmd(), ["schtasks", "/Query", "/TN", WINDOWS_TASK_NAME])
        self.assertEqual(build_windows_schtasks_delete_cmd(), ["schtasks", "/Delete", "/TN", WINDOWS_TASK_NAME, "/F"])

    def test_homebrew_cellar_opt_resolution(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hermes-brew-test-") as tmp:
            prefix = Path(tmp)
            cellar_bin = prefix / "Cellar" / "hermes-icon" / "0.1.0" / "libexec" / "bin"
            cellar_bin.mkdir(parents=True)
            (cellar_bin / "hermes-icon").write_text("#!/bin/sh\n", encoding="utf-8")
            opt_bin = prefix / "opt" / "hermes-icon" / "bin"
            opt_bin.mkdir(parents=True)
            (opt_bin / "hermes-icon").write_text("#!/bin/sh\n", encoding="utf-8")
            self.assertEqual(_launcher_bin(cellar_bin), opt_bin / "hermes-icon")

    def test_watcher_non_blocking_when_locked(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hermes-lock-test-") as tmp:
            lock_p = Path(tmp) / "replacer.lock"
            # Spawn a child holding replacer.lock in watcher mode
            holder_code = (
                "import fcntl, json, os, sys, time; "
                "fd = os.open(sys.argv[1], os.O_CREAT | os.O_RDWR, 0o644); "
                "fcntl.flock(fd, fcntl.LOCK_EX); "
                "os.ftruncate(fd, 0); "
                "os.write(fd, json.dumps({'pid': os.getpid(), 'mode': 'watcher', 'ts': time.time()}).encode()); "
                "sys.stdout.write('READY\\n'); sys.stdout.flush(); "
                "time.sleep(30)"
            )
            proc = subprocess.Popen(
                [sys.executable, "-c", holder_code, str(lock_p)],
                stdout=subprocess.PIPE,
                text=True,
            )
            try:
                assert proc.stdout is not None
                self.assertEqual(proc.stdout.readline().strip(), "READY")
                # Interactive lock must preempt the watcher and acquire immediately (<2s)
                t0 = time.monotonic()
                with replacer_lock(lock_p, blocking=True, mode="interactive", preempt_watcher=True, timeout=5.0):
                    dt = time.monotonic() - t0
                self.assertLess(dt, 2.0)
            finally:
                if proc.stdout is not None:
                    proc.stdout.close()
                if proc.poll() is None:
                    proc.kill()
                proc.wait()


class TestTuiAlignment(unittest.TestCase):
    def test_tui_preview_column_alignment_all_presets_and_widths(self) -> None:
        ansi_strip = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
        for term_cols, expected_preview_len, expected_rows in ((90, 36, 18), (125, 75, 18)):
            cache: dict[str, list[str]] = {}
            for active_preset in ("disco-girl", "caduceus", "shield"):
                cfg = IconConfig(mode="preset", preset=active_preset)
                for selected_idx in range(len(PRESET_ORDER)):
                    frame = render_tui_frame(cfg, selected_idx, cache, term_cols=term_cols)
                    plain = ansi_strip.sub("", frame)
                    self.assertIn("[g] Web GUI", plain)
                    self.assertIn("1-9]", plain)
                    if term_cols >= 116:
                        hdr_lines = [ln for ln in plain.splitlines() if "Light" in ln and "Dark" in ln]
                        self.assertEqual(len(hdr_lines), 1)
                        self.assertEqual(hdr_lines[0].index("Light"), LEFT_COL_WIDTH)
                        self.assertEqual(hdr_lines[0].index("Dark"), LEFT_COL_WIDTH + 36 + 3)
                    preview_lines = [
                        ansi_strip.sub("", ln)
                        for ln in frame.splitlines()
                        if "▀" in ln
                    ]
                    self.assertEqual(len(preview_lines), expected_rows)
                    for pl in preview_lines:
                        self.assertEqual(
                            pl.index("▀"),
                            LEFT_COL_WIDTH,
                            f"Misaligned preview row (term_cols={term_cols}, active={active_preset}, sel={selected_idx}): {pl!r}",
                        )
                        self.assertEqual(len(pl), LEFT_COL_WIDTH + expected_preview_len)


class TestLiveIntegrationAndSelfHealing(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._orig_cfg = load_config()

    @classmethod
    def tearDownClass(cls) -> None:
        apply_icon(cls._orig_cfg)

    def test_live_apply_backup_codesign_and_simulated_update_heal(self) -> None:
        # 1. Verify original backup exists and starts with 2812a3db for icon.icns
        manifest = load_backup_manifest()
        self.assertIsNotNone(manifest)
        self.assertTrue(
            manifest["files"]["repo/apps/desktop/assets/icon.icns"]["sha256"].startswith("2812a3db")
        )

        # 2. Stale update lock (Oct 26) must NOT trigger update-in-progress block
        busy, reason = is_update_in_progress()
        self.assertFalse(busy, f"Stale lock erroneously blocked: {reason}")

        # 3. Verify Hermes.app Assets.car, icon.icns (16..1024), app.asar integrity, and codesign
        res_dir = HERMES_APP / "Contents" / "Resources"
        self.assertTrue((res_dir / "Assets.car").exists())
        with Image.open(res_dir / "icon.icns") as icns_img:
            self.assertEqual(icns_img.size, (1024, 1024))
            pt_sizes = {(w, h) for w, h, _ in icns_img.info.get("sizes", [])}
            px_sizes = {(w * s, h * s) for w, h, s in icns_img.info.get("sizes", [])}
            self.assertIn((16, 16), pt_sizes)
            self.assertIn((512, 512), pt_sizes)
            self.assertIn((1024, 1024), px_sizes)
            self.assertIn((512, 512), px_sizes)
            self.assertIn((32, 32), px_sizes)

        ok, errs = verify_asar_integrity(
            res_dir / "app.asar",
            HERMES_APP / "Contents" / "Info.plist",
            unpacked_dir=res_dir / "app.asar.unpacked",
            check_paths=[
                "public/apple-touch-icon.png",
                "public/nous-girl.png",
                "public/nous-girl-dark.png",
                "dist/apple-touch-icon.png",
                "dist/nous-girl.png",
                "dist/nous-girl-dark.png",
                "assets/icon.icns",
                "assets/icon.png",
                "assets/icon-mac.png",
            ],
        )
        self.assertTrue(ok, f"Live ASAR integrity check failed: {errs}")

        cs = subprocess.run(
            ["/usr/bin/codesign", "--verify", "--strict", str(HERMES_APP)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(cs.returncode, 0, f"codesign verify failed: {cs.stderr}")

        # 4. Verify upstream generate_icons.py --source/--out + --check compatibility
        up_res = apply_to_repo(
            IconConfig(mode="preset", preset="disco-girl"),
            repo=HERMES_REPO,
            run_upstream_generator=True,
            run_upstream_check=True,
        )
        self.assertIn("[ok]", up_res["check_stdout"])

        # 5. Simulated update restoration test:
        # Age applied_at past 10s cooldown first so lock check is exercised deterministically
        st = load_state()
        st["applied_at"] = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()
        save_state(st)
        with replacer_lock(blocking=True, mode="interactive"):
            skip_res = check_and_heal(apply_if_needed=True)
            self.assertEqual(skip_res["action"], "skipped_locked")

        # Verify cooldown skips if applied_at is <10s ago
        st["applied_at"] = datetime.now(timezone.utc).isoformat()
        save_state(st)
        cool_res = check_and_heal(apply_if_needed=True)
        self.assertEqual(cool_res["action"], "skipped_cooldown")

        # Age applied_at past 10s cooldown and restore original files to simulate `hermes update`
        st["applied_at"] = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()
        save_state(st)
        shutil.copy2(
            BACKUPS_ORIGINAL_DIR / "hermes_app" / "Contents" / "Resources" / "icon.icns",
            res_dir / "icon.icns",
        )
        shutil.copy2(
            BACKUPS_ORIGINAL_DIR / "repo" / "assets" / "nous-girl-black.svg",
            HERMES_REPO / "assets" / "nous-girl-black.svg",
        )

        # CLI `hermes-icon check` should detect drift & exit 1
        cli_chk = subprocess.run(
            [str(BIN_HERMES_ICON), "check", "--json"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(cli_chk.returncode, 1)
        chk_data = json.loads(cli_chk.stdout)
        self.assertTrue(chk_data["needs_apply"])
        self.assertIn("hermes_app/Contents/Resources/icon.icns", chk_data["restored_to_original"])

        # CLI `hermes-icon check --apply` should automatically heal
        cli_heal = subprocess.run(
            [str(BIN_HERMES_ICON), "check", "--apply", "--json"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(cli_heal.returncode, 0, cli_heal.stderr)
        heal_data = json.loads(cli_heal.stdout)
        self.assertEqual(heal_data["action"], "reapplied")

        # Verify fast check passes after heal & codesign remains valid
        t0 = time.monotonic()
        post_chk = subprocess.run(
            [str(BIN_HERMES_ICON), "check", "--json"],
            capture_output=True,
            text=True,
        )
        elapsed_ms = (time.monotonic() - t0) * 1000
        self.assertEqual(post_chk.returncode, 0)
        self.assertFalse(json.loads(post_chk.stdout)["needs_apply"])

        cs2 = subprocess.run(
            ["/usr/bin/codesign", "--verify", "--strict", str(HERMES_APP)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(cs2.returncode, 0)

        # 6. Verify watcher (launchd + git hooks) is loaded & installed
        self.assertTrue(is_launchd_loaded(), "launchd agent should be loaded")
        hooks = git_hooks_status()
        self.assertTrue(all(hooks.values()), f"Missing git hooks: {hooks}")
        _ = elapsed_ms


if __name__ == "__main__":
    unittest.main(verbosity=2)
