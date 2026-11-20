"""Isolated launcher entrypoint for hermes-icon."""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import site
import subprocess
import sys
from pathlib import Path

SRC_DIR = str(Path(__file__).resolve().parent / "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from hermes_icon.config import (  # noqa: E402
    candidate_hermes_homes,
    discover_packaged_payload_dirs,
    resolve_replacer_root,
)


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


def _clean_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME")}


def _is_windows_store_stub(path: Path) -> bool:
    if sys.platform != "win32":
        return False
    return "\\microsoft\\windowsapps\\" in os.path.normcase(str(path))


def _probe_python(cand: Path, site_dir: Path | None = None) -> bool:
    """Return True if ``cand`` can import both PIL and resvg_py."""
    if not cand.is_file() or _is_windows_store_stub(cand):
        return False
    if site_dir is not None:
        cmd = [
            str(cand),
            "-I",
            "-c",
            "import site, sys; site.addsitedir(sys.argv[1]); import PIL, resvg_py",
            str(site_dir),
        ]
    else:
        cmd = [str(cand), "-I", "-c", "import PIL, resvg_py"]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=10, env=_clean_env())
        return proc.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _python_in_venv(venv_dir: Path) -> Path:
    if sys.platform == "win32":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _collect_site_dirs() -> list[Path]:
    dirs: list[Path] = []
    for home in candidate_hermes_homes():
        installs = home / "installs"
        if installs.is_dir():
            for sp in sorted(installs.glob("*/environments/*/venv/Lib/site-packages")):
                if sp.is_dir():
                    dirs.append(sp)
            for sp in sorted(installs.glob("*/environments/*/venv/lib/python*/site-packages")):
                if sp.is_dir():
                    dirs.append(sp)
    for payload in discover_packaged_payload_dirs():
        for pat in ("venv/Lib/site-packages", "venv/lib/python*/site-packages"):
            for sp in sorted(payload.glob(pat)):
                if sp.is_dir():
                    dirs.append(sp)
    return dirs


def _collect_tools_pythons() -> list[Path]:
    pythons: list[Path] = []
    exe_patterns = ("python*/python.exe", "python*/bin/python") if sys.platform == "win32" else ("python*/bin/python",)
    roots: list[Path] = []
    for home in candidate_hermes_homes():
        roots.append(home / "tools")
        installs = home / "installs"
        if installs.is_dir():
            roots.extend(sorted(installs.glob("*/tools")))
    for payload in discover_packaged_payload_dirs():
        roots.append(payload / "tools")

    for root in roots:
        if not root.is_dir():
            continue
        for pat in exe_patterns:
            for cand in sorted(root.glob(pat)):
                if cand.is_file():
                    pythons.append(cand)
    return pythons


def _find_python_and_sitedir() -> tuple[Path, Path | None] | None:
    replacer_root = resolve_replacer_root()
    own_venv_py = _python_in_venv(replacer_root / ".venv")
    if _probe_python(own_venv_py):
        return own_venv_py, None

    direct_candidates: list[Path] = []
    for hermes_home in candidate_hermes_homes():
        direct_candidates.append(_python_in_venv(hermes_home / "icon-replacer" / ".venv"))
        installs = hermes_home / "installs"
        if installs.is_dir():
            for facts in sorted(installs.glob("*/facts.json")):
                with contextlib.suppress(Exception):
                    data = json.loads(facts.read_text(encoding="utf-8"))
                    env_dir = data.get("packages", {}).get("venv", {}).get("environment")
                    if env_dir:
                        direct_candidates.append(_python_in_venv(Path(env_dir)))
            for pat in ("*/environments/*/venv/Scripts/python.exe", "*/environments/*/venv/bin/python"):
                direct_candidates.extend(sorted(installs.glob(pat)))
        for sub in (".venv", "venv"):
            direct_candidates.append(_python_in_venv(hermes_home / "hermes-agent" / sub))

    for payload in discover_packaged_payload_dirs():
        for sub in ("venv", ".venv"):
            direct_candidates.append(_python_in_venv(payload / sub))
            direct_candidates.append(_python_in_venv(payload / "repo" / sub))

    seen: set[Path] = set()
    for cand in direct_candidates:
        if cand in seen:
            continue
        seen.add(cand)
        if _probe_python(cand):
            return cand, None

    # Hermes PM on Windows sometimes pairs tools/python-*/python.exe with venv/Lib/site-packages
    site_dirs = _collect_site_dirs()
    if site_dirs:
        cur_py = Path(sys.executable)
        tool_pythons = [*[p for p in _collect_tools_pythons() if p not in seen], cur_py]
        for sp_dir in site_dirs:
            for py_cand in tool_pythons:
                if _probe_python(py_cand, sp_dir):
                    return py_cand, sp_dir

    return None


def _find_hermes_python() -> Path | None:
    found = _find_python_and_sitedir()
    return found[0] if found is not None else None


def _find_uv_binary() -> Path | None:
    which_uv = shutil.which("uv")
    if which_uv:
        p = Path(which_uv)
        if p.is_file() and not _is_windows_store_stub(p):
            return p

    uv_name = "uv.exe" if sys.platform == "win32" else "uv"
    candidates: list[Path] = []
    for home in candidate_hermes_homes():
        candidates.extend(sorted((home / "tools").glob(f"uv*/{uv_name}")) if (home / "tools").is_dir() else [])
        candidates.append(home / "bin" / uv_name)
    for payload in discover_packaged_payload_dirs():
        candidates.extend(sorted((payload / "tools").glob(f"uv*/{uv_name}")) if (payload / "tools").is_dir() else [])
        candidates.append(payload / "bin" / uv_name)
    candidates.append(Path.home() / ".local" / "bin" / uv_name)
    if sys.platform == "win32":
        candidates.extend(
            [
                Path.home() / "scoop" / "shims" / "uv.exe",
                Path.home() / "scoop" / "apps" / "uv" / "current" / "uv.exe",
            ]
        )

    for cand in candidates:
        if cand.is_file() and not _is_windows_store_stub(cand):
            return cand
    return None


def _bootstrap_deps(replacer_root: Path) -> tuple[Path, Path | None]:
    print("hermes-icon: installing runtime dependencies (pillow, resvg-py)...", file=sys.stderr, flush=True)
    replacer_root.mkdir(parents=True, exist_ok=True)
    venv_dir = replacer_root / ".venv"
    venv_py = _python_in_venv(venv_dir)
    site_dir = replacer_root / "site-packages"
    env = _clean_env()

    # Strategy A: uv (fast isolated venv)
    uv_bin = _find_uv_binary()
    if uv_bin is not None:
        venv_cmd = [str(uv_bin), "venv"]
        if venv_dir.exists():
            venv_cmd.append("--clear")
        venv_cmd.extend([str(venv_dir), "--python", sys.executable])
        proc = subprocess.run(venv_cmd, capture_output=True, text=True, env=env)
        if proc.returncode != 0:
            fallback_cmd = [str(uv_bin), "venv"]
            if venv_dir.exists():
                fallback_cmd.append("--clear")
            fallback_cmd.append(str(venv_dir))
            proc = subprocess.run(fallback_cmd, capture_output=True, text=True, env=env)
        if proc.returncode == 0 and venv_py.is_file():
            install_proc = subprocess.run(
                [str(uv_bin), "pip", "install", "--python", str(venv_py), "-q", "pillow", "resvg-py"],
                capture_output=True,
                text=True,
                env=env,
            )
            if install_proc.returncode == 0 and _probe_python(venv_py):
                return venv_py, None

    # Strategy B: stdlib python -m venv + pip
    venv_args = [sys.executable, "-m", "venv"]
    if venv_dir.exists():
        venv_args.append("--clear")
    venv_args.append(str(venv_dir))
    proc_b = subprocess.run(venv_args, capture_output=True, text=True, env=env)
    if proc_b.returncode == 0 and venv_py.is_file():
        install_b = subprocess.run(
            [str(venv_py), "-m", "pip", "install", "--disable-pip-version-check", "-q", "pillow", "resvg-py"],
            capture_output=True,
            text=True,
            env=env,
        )
        if install_b.returncode == 0 and _probe_python(venv_py):
            return venv_py, None

    # Strategy C: pip install --target <REPLACER_ROOT>/site-packages
    site_dir.mkdir(parents=True, exist_ok=True)
    install_c = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "-q",
            "--target",
            str(site_dir),
            "pillow",
            "resvg-py",
        ],
        capture_output=True,
        text=True,
        env=env,
    )
    if install_c.returncode == 0 and _probe_python(Path(sys.executable), site_dir):
        return Path(sys.executable), site_dir

    raise RuntimeError(
        "hermes-icon: failed to install runtime dependencies (pillow, resvg-py). "
        "Ensure Python 3.11+ with pip or uv is available."
    )


def _ensure_deps_or_reexec() -> None:
    env_site = os.environ.get("_HERMES_ICON_SITE_DIR", "").strip()
    if env_site and Path(env_site).is_dir():
        site.addsitedir(env_site)

    site_dir = resolve_replacer_root() / "site-packages"
    if site_dir.is_dir():
        site.addsitedir(str(site_dir))

    try:
        import PIL  # noqa: F401
        import resvg_py  # noqa: F401
        return
    except ImportError:
        if os.environ.get("_HERMES_ICON_REEXEC") == "1":
            raise
        found = _find_python_and_sitedir()
        if found is None:
            found = _bootstrap_deps(resolve_replacer_root())
        target_py, target_site = found
        if target_py.resolve() == Path(sys.executable).resolve():
            if target_site is not None and target_site.is_dir():
                site.addsitedir(str(target_site))
                import PIL  # noqa: F401
                import resvg_py  # noqa: F401
                return
            raise

        env = _clean_env()
        env["_HERMES_ICON_REEXEC"] = "1"
        if target_site is not None:
            env["_HERMES_ICON_SITE_DIR"] = str(target_site)
        proc = subprocess.run([str(target_py), "-I", str(Path(__file__).resolve()), *sys.argv[1:]], env=env)
        sys.exit(proc.returncode)


if __name__ == "__main__":
    _init_windows_console()
    _ensure_deps_or_reexec()
    if "--bootstrap" in sys.argv[1:]:
        sys.exit(0)
    from hermes_icon.cli import main

    sys.exit(main())
