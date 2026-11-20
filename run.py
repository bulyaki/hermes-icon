"""Isolated launcher entrypoint for hermes-icon."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

SRC_DIR = str(Path(__file__).resolve().parent / "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)


def _find_hermes_python() -> Path | None:
    hermes_home = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
    installs = hermes_home / "installs"
    if not installs.is_dir():
        return None

    rel_bins = (
        ("Scripts", "python.exe") if sys.platform == "win32" else ("bin", "python")
    )
    for facts in sorted(installs.glob("*/facts.json")):
        try:
            data = json.loads(facts.read_text(encoding="utf-8"))
            env_dir = data.get("packages", {}).get("venv", {}).get("environment")
            if env_dir:
                cand = Path(env_dir).joinpath(*rel_bins)
                if cand.is_file():
                    return cand
        except Exception:
            pass

    for pattern in ("*/environments/*/venv/Scripts/python.exe", "*/environments/*/venv/bin/python"):
        for cand in sorted(installs.glob(pattern)):
            if cand.is_file():
                return cand
    return None


def _ensure_deps_or_reexec() -> None:
    try:
        import PIL  # noqa: F401
        import resvg_py  # noqa: F401
        return
    except ImportError:
        if os.environ.get("_HERMES_ICON_REEXEC") == "1":
            raise
        hermes_py = _find_hermes_python()
        if hermes_py is None or hermes_py.resolve() == Path(sys.executable).resolve():
            raise
        env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME")}
        env["_HERMES_ICON_REEXEC"] = "1"
        proc = subprocess.run([str(hermes_py), "-I", str(Path(__file__).resolve()), *sys.argv[1:]], env=env)
        sys.exit(proc.returncode)


if __name__ == "__main__":
    _ensure_deps_or_reexec()
    from hermes_icon.cli import main

    sys.exit(main())
