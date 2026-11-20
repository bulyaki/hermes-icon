"""Local web GUI picker for hermes-icon served on 127.0.0.1:<ephemeral_port>."""

from __future__ import annotations

import base64
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .applier import apply_icon, inspect_surfaces
from .backup import restore_original_icons
from .config import (
    CUSTOM_ASSETS_DIR,
    DEFAULT_BG_DARK,
    DEFAULT_BG_LIGHT,
    DEFAULT_FG_DARK,
    DEFAULT_FG_LIGHT,
    IconConfig,
    load_config,
    normalize_hex_color,
    save_config,
)
from .presets import PRESET_ORDER, PRESETS
from .renderer import IconRenderer
from .watcher import install_watcher, watcher_status

HTML_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Hermes Icon Picker</title>
<style>
  :root {
    --bg: #0b0e14;
    --panel: #131922;
    --panel-2: #19212d;
    --border: #283344;
    --text: #eef2f7;
    --muted: #93a1b5;
    --accent: #56b6f7;
    --accent-2: #38d399;
    --danger: #f87171;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", sans-serif;
    background: radial-gradient(circle at top right, #162235 0%, var(--bg) 55%);
    color: var(--text);
    min-height: 100vh;
    padding: 28px 24px 64px;
  }
  .wrap { max-width: 1120px; margin: 0 auto; }
  header {
    display: flex;
    flex-wrap: wrap;
    justify-content: space-between;
    align-items: center;
    gap: 16px;
    margin-bottom: 24px;
  }
  h1 { margin: 0; font-size: 26px; letter-spacing: -0.02em; }
  .subtitle { color: var(--muted); font-size: 14px; margin-top: 4px; }
  .status-pill {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 8px 14px;
    border-radius: 999px;
    background: var(--panel);
    border: 1px solid var(--border);
    font-size: 13px;
  }
  .dot { width: 9px; height: 9px; border-radius: 50%; background: var(--accent-2); }
  .dot.warn { background: #fbbf24; }
  .layout {
    display: grid;
    grid-template-columns: 1fr 340px;
    gap: 20px;
    align-items: start;
  }
  @media (max-width: 900px) {
    .layout { grid-template-columns: 1fr; }
  }
  .card {
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 20px;
  }
  .card h2 { margin: 0 0 14px; font-size: 16px; font-weight: 600; }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(210px, 1fr));
    gap: 14px;
  }
  .preset {
    background: var(--panel-2);
    border: 2px solid transparent;
    border-radius: 14px;
    padding: 14px;
    cursor: pointer;
    transition: border-color .15s, transform .12s, background .15s;
    text-align: left;
    color: inherit;
  }
  .preset:hover { border-color: #3b4b63; transform: translateY(-1px); }
  .preset.selected { border-color: var(--accent); background: #1a2638; }
  .pair {
    display: flex;
    gap: 10px;
    justify-content: center;
    margin-bottom: 12px;
    padding: 10px;
    border-radius: 10px;
    background: repeating-conic-gradient(#1f2735 0% 25%, #181f2b 0% 50%) 50% / 14px 14px;
  }
  .pair img {
    width: 72px;
    height: 72px;
    border-radius: 16px;
    object-fit: contain;
  }
  .preset-title {
    font-weight: 600;
    font-size: 14px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 6px;
  }
  .badge {
    font-size: 11px;
    padding: 2px 7px;
    border-radius: 999px;
    background: rgba(56, 211, 153, 0.16);
    color: var(--accent-2);
  }
  .preset-desc { font-size: 12px; color: var(--muted); margin-top: 4px; line-height: 1.35; }
  .dropzone {
    border: 2px dashed #394860;
    border-radius: 14px;
    padding: 18px;
    text-align: center;
    cursor: pointer;
    background: rgba(25, 33, 45, 0.65);
    transition: border-color .15s, background .15s;
  }
  .dropzone.drag { border-color: var(--accent); background: rgba(86, 182, 247, 0.1); }
  .dropzone input { display: none; }
  .controls { display: grid; gap: 14px; margin-top: 14px; }
  .row { display: flex; justify-content: space-between; align-items: center; gap: 10px; font-size: 13px; }
  .color-group { display: flex; align-items: center; gap: 8px; }
  input[type="color"] {
    width: 34px; height: 28px; padding: 0; border: 1px solid var(--border);
    border-radius: 6px; background: transparent; cursor: pointer;
  }
  input[type="range"] { width: 150px; }
  .btn {
    width: 100%;
    padding: 12px 16px;
    border: none;
    border-radius: 11px;
    font-size: 14px;
    font-weight: 600;
    cursor: pointer;
    transition: opacity .15s, transform .1s;
  }
  .btn:hover { opacity: 0.94; }
  .btn:active { transform: scale(0.99); }
  .btn:disabled { opacity: 0.5; cursor: wait; }
  .btn-primary { background: linear-gradient(135deg, #56b6f7, #3b82f6); color: #fff; }
  .btn-secondary { background: var(--panel-2); color: var(--text); border: 1px solid var(--border); }
  .btn-danger { background: rgba(248, 113, 113, 0.14); color: var(--danger); border: 1px solid rgba(248, 113, 113, 0.35); }
  .meta-list { font-size: 12px; color: var(--muted); display: grid; gap: 6px; margin-top: 10px; }
  .meta-item { display: flex; justify-content: space-between; gap: 8px; }
  .toast {
    margin-top: 12px;
    padding: 10px 12px;
    border-radius: 10px;
    font-size: 13px;
    display: none;
  }
  .toast.ok { display: block; background: rgba(56, 211, 153, 0.15); color: #6ee7b7; border: 1px solid rgba(56, 211, 153, 0.35); }
  .toast.err { display: block; background: rgba(248, 113, 113, 0.15); color: #fca5a5; border: 1px solid rgba(248, 113, 113, 0.35); }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div>
      <h1>Hermes Icon Picker</h1>
      <div class="subtitle">Replace the Hermes app icon across repo, Assets.car, app.asar, Electron &amp; Web UI</div>
    </div>
    <div class="status-pill" id="status-pill">
      <span class="dot" id="status-dot"></span>
      <span id="status-text">Loading status…</span>
    </div>
  </header>

  <div class="layout">
    <div class="card">
      <h2>Curated Presets</h2>
      <div class="grid" id="preset-grid"></div>
    </div>

    <div style="display: grid; gap: 18px;">
      <div class="card">
        <h2>Selected Preview</h2>
        <div class="pair" id="live-pair">
          <img id="preview-light" alt="Light preview" />
          <img id="preview-dark" alt="Dark preview" />
        </div>
        <div id="selection-label" style="font-size: 13px; color: var(--muted); text-align: center;"></div>

        <div class="controls">
          <div class="row">
            <span>Light plate</span>
            <div class="color-group">
              <input type="color" id="bg-light" value="#ffffff" />
              <code id="bg-light-hex">#ffffff</code>
            </div>
          </div>
          <div class="row">
            <span>Dark plate</span>
            <div class="color-group">
              <input type="color" id="bg-dark" value="#0d1117" />
              <code id="bg-dark-hex">#0d1117</code>
            </div>
          </div>
          <div class="row">
            <span>Icon scale (<span id="scale-val">0.78</span>)</span>
            <input type="range" id="scale" min="0.45" max="1.0" step="0.02" value="0.78" />
          </div>
          <div class="row">
            <label><input type="checkbox" id="full-bleed" /> Full-bleed custom mask</label>
            <button type="button" id="reset-colors" class="btn-secondary" style="padding: 5px 10px; border-radius: 7px; font-size: 12px; cursor: pointer;">Reset</button>
          </div>
        </div>
      </div>

      <div class="card">
        <h2>Custom Icon (.svg, .png, .icns, .ico, .jpg, .webp)</h2>
        <label class="dropzone" id="dropzone">
          <input type="file" id="custom-file" accept=".svg,.png,.icns,.ico,.jpg,.jpeg,.webp" />
          <div style="font-weight: 600; font-size: 13px;">Drop icon here or click to browse</div>
          <div id="custom-filename" style="font-size: 12px; color: var(--muted); margin-top: 6px;">No custom file uploaded</div>
        </label>
        <div style="margin-top: 10px; display: flex; justify-content: space-between; align-items: center; font-size: 12px; color: var(--muted);">
          <span>Optional dark-mode variant:</span>
          <label style="color: var(--accent); cursor: pointer;">
            Choose dark file
            <input type="file" id="custom-dark-file" accept=".svg,.png,.icns,.ico,.jpg,.jpeg,.webp" style="display:none;" />
          </label>
        </div>
        <div id="custom-dark-filename" style="font-size: 11px; color: var(--muted); margin-top: 3px;"></div>
      </div>

      <div class="card">
        <div style="display: grid; gap: 10px;">
          <button class="btn btn-primary" id="apply-btn">Apply &amp; Watch</button>
          <button class="btn btn-danger" id="restore-btn">Restore Original nous-girl</button>
        </div>
        <div id="toast" class="toast"></div>
        <div class="meta-list" id="meta-list"></div>
      </div>
    </div>
  </div>
</div>

<script>
const state = {
  mode: "preset",
  preset: "disco-girl",
  activePreset: "disco-girl",
  activeMode: "preset",
  bg_light: "#ffffff",
  bg_dark: "#0d1117",
  scale: 0.78,
  full_bleed: false,
  custom_token: null,
  custom_dark_token: null,
  custom_name: null,
  presets: [],
};

function previewUrl(params) {
  const q = new URLSearchParams(params);
  return "/api/preview?" + q.toString();
}

function updateLivePreview() {
  const base = {
    mode: state.mode,
    preset: state.preset,
    bg_light: state.bg_light,
    bg_dark: state.bg_dark,
    scale: state.scale,
    full_bleed: state.full_bleed ? "1" : "0",
  };
  if (state.custom_token) base.custom_token = state.custom_token;
  if (state.custom_dark_token) base.custom_dark_token = state.custom_dark_token;
  document.getElementById("preview-light").src = previewUrl({ ...base, appearance: "light", _t: Date.now() });
  document.getElementById("preview-dark").src = previewUrl({ ...base, appearance: "dark", _t: Date.now() });
  document.getElementById("selection-label").textContent =
    state.mode === "custom"
      ? "Custom: " + (state.custom_name || "uploaded icon")
      : "Preset: " + state.preset;
}

function renderPresets() {
  const grid = document.getElementById("preset-grid");
  grid.innerHTML = "";
  for (const p of state.presets) {
    const el = document.createElement("button");
    el.type = "button";
    const selected = state.mode === "preset" && state.preset === p.id;
    const isActive = state.activeMode === "preset" && state.activePreset === p.id;
    el.className = "preset" + (selected ? " selected" : "");
    el.innerHTML = `
      <div class="pair">
        <img src="${previewUrl({ mode: "preset", preset: p.id, appearance: "light", bg_light: state.bg_light, scale: state.scale })}" alt="${p.name} light"/>
        <img src="${previewUrl({ mode: "preset", preset: p.id, appearance: "dark", bg_dark: state.bg_dark, scale: state.scale })}" alt="${p.name} dark"/>
      </div>
      <div class="preset-title">
        <span>${p.name}</span>
        ${isActive ? '<span class="badge">active</span>' : ""}
      </div>
      <div class="preset-desc">${p.tagline}</div>
    `;
    el.onclick = () => {
      state.mode = "preset";
      state.preset = p.id;
      renderPresets();
      updateLivePreview();
    };
    grid.appendChild(el);
  }
}

function showToast(msg, ok = true) {
  const t = document.getElementById("toast");
  t.className = "toast " + (ok ? "ok" : "err");
  t.textContent = msg;
}

async function refreshStatus() {
  const r = await fetch("/api/status");
  const data = await r.json();
  state.presets = data.presets;
  state.activePreset = data.config.preset;
  state.activeMode = data.config.mode;
  if (!state._initialized) {
    state.mode = data.config.mode;
    state.preset = data.config.preset || "disco-girl";
    state.bg_light = data.config.bg_light || "#ffffff";
    state.bg_dark = data.config.bg_dark || "#0d1117";
    state.scale = data.config.scale || 0.78;
    state.full_bleed = Boolean(data.config.full_bleed);
    document.getElementById("bg-light").value = state.bg_light;
    document.getElementById("bg-light-hex").textContent = state.bg_light;
    document.getElementById("bg-dark").value = state.bg_dark;
    document.getElementById("bg-dark-hex").textContent = state.bg_dark;
    document.getElementById("scale").value = state.scale;
    document.getElementById("scale-val").textContent = Number(state.scale).toFixed(2);
    document.getElementById("full-bleed").checked = state.full_bleed;
    if (data.config.mode === "custom" && data.config.custom_path) {
      state.custom_name = data.config.custom_path.split("/").pop();
      document.getElementById("custom-filename").textContent = state.custom_name;
    }
    state._initialized = true;
  }

  const s = data.surfaces;
  const w = data.watcher;
  const wActive = Boolean(w.active ?? w.launchd_loaded);
  const dot = document.getElementById("status-dot");
  const st = document.getElementById("status-text");
  if (!s.needs_apply && wActive) {
    dot.className = "dot";
    st.textContent = `Synced (${s.matching}/${s.total_surfaces}) • Watcher active`;
  } else {
    dot.className = "dot warn";
    st.textContent = `Needs apply (${s.matching}/${s.total_surfaces}) • Watcher ${wActive ? "on" : "off"}`;
  }

  const meta = document.getElementById("meta-list");
  meta.innerHTML = `
    <div class="meta-item"><span>Active icon</span><span>${data.config.mode === "preset" ? data.config.preset : "custom"}</span></div>
    <div class="meta-item"><span>Surfaces synced</span><span>${s.matching} / ${s.total_surfaces}</span></div>
    <div class="meta-item"><span>Watcher (${w.backend || "launchd"})</span><span>${wActive ? "active" : "inactive"}</span></div>
    <div class="meta-item"><span>Git hooks</span><span>${Object.values(w.git_hooks).every(Boolean) ? "installed" : "partial/none"}</span></div>
  `;
  renderPresets();
  updateLivePreview();
}

async function uploadCustom(file, isDark = false) {
  const b64 = await new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",")[1]);
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
  const resp = await fetch("/api/upload", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ filename: file.name, data_base64: b64 }),
  });
  const res = await resp.json();
  if (!resp.ok) throw new Error(res.error || "Upload failed");
  if (isDark) {
    state.custom_dark_token = res.token;
    document.getElementById("custom-dark-filename").textContent = "Dark: " + file.name;
  } else {
    state.custom_token = res.token;
    state.custom_name = file.name;
    state.mode = "custom";
    document.getElementById("custom-filename").textContent = "Selected: " + file.name;
  }
  renderPresets();
  updateLivePreview();
}

document.getElementById("custom-file").addEventListener("change", (e) => {
  if (e.target.files[0]) uploadCustom(e.target.files[0], false).catch((err) => showToast(err.message, false));
});
document.getElementById("custom-dark-file").addEventListener("change", (e) => {
  if (e.target.files[0]) uploadCustom(e.target.files[0], true).catch((err) => showToast(err.message, false));
});

const dz = document.getElementById("dropzone");
dz.addEventListener("dragover", (e) => { e.preventDefault(); dz.classList.add("drag"); });
dz.addEventListener("dragleave", () => dz.classList.remove("drag"));
dz.addEventListener("drop", (e) => {
  e.preventDefault();
  dz.classList.remove("drag");
  if (e.dataTransfer.files[0]) uploadCustom(e.dataTransfer.files[0], false).catch((err) => showToast(err.message, false));
});

document.getElementById("bg-light").addEventListener("input", (e) => {
  state.bg_light = e.target.value;
  document.getElementById("bg-light-hex").textContent = state.bg_light;
  updateLivePreview();
});
document.getElementById("bg-dark").addEventListener("input", (e) => {
  state.bg_dark = e.target.value;
  document.getElementById("bg-dark-hex").textContent = state.bg_dark;
  updateLivePreview();
});
document.getElementById("scale").addEventListener("input", (e) => {
  state.scale = parseFloat(e.target.value);
  document.getElementById("scale-val").textContent = state.scale.toFixed(2);
  updateLivePreview();
});
document.getElementById("full-bleed").addEventListener("change", (e) => {
  state.full_bleed = e.target.checked;
  updateLivePreview();
});
document.getElementById("reset-colors").addEventListener("click", () => {
  state.bg_light = "#ffffff";
  state.bg_dark = "#0d1117";
  state.scale = 0.78;
  state.full_bleed = false;
  document.getElementById("bg-light").value = state.bg_light;
  document.getElementById("bg-light-hex").textContent = state.bg_light;
  document.getElementById("bg-dark").value = state.bg_dark;
  document.getElementById("bg-dark-hex").textContent = state.bg_dark;
  document.getElementById("scale").value = state.scale;
  document.getElementById("scale-val").textContent = "0.78";
  document.getElementById("full-bleed").checked = false;
  renderPresets();
  updateLivePreview();
});

document.getElementById("apply-btn").addEventListener("click", async () => {
  const btn = document.getElementById("apply-btn");
  btn.disabled = true;
  btn.textContent = "Applying everywhere…";
  try {
    const resp = await fetch("/api/apply", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        mode: state.mode,
        preset: state.preset,
        bg_light: state.bg_light,
        bg_dark: state.bg_dark,
        scale: state.scale,
        full_bleed: state.full_bleed,
        custom_token: state.custom_token,
        custom_dark_token: state.custom_dark_token,
      }),
    });
    const res = await resp.json();
    if (!resp.ok) throw new Error(res.error || "Apply failed");
    const elapsed = res.elapsed_s != null ? `${res.elapsed_s}s` : "done";
    if (res.auto_quit) {
      showToast(`Applied in ${elapsed}! Closing picker…`);
      setTimeout(() => {
        window.close();
        document.body.innerHTML = `
          <div style="max-width:520px;margin:96px auto;padding:28px;border-radius:16px;background:#131922;border:1px solid #283344;text-align:center;">
            <div style="font-size:28px;margin-bottom:10px;color:#38d399;">✓</div>
            <h2 style="margin:0 0 8px;">Icon applied everywhere in ${elapsed}</h2>
            <p style="margin:0;color:#93a1b5;font-size:14px;">All Hermes targets, macOS Assets.car, app.asar, and watcher are updated. You may close this tab.</p>
          </div>
        `;
      }, 600);
      return;
    }
    showToast(`Applied in ${elapsed}! ${res.apply.repo.targets_written} repo targets + Hermes.app + watcher active.`);
    await refreshStatus();
  } catch (err) {
    showToast(err.message, false);
  } finally {
    btn.disabled = false;
    btn.textContent = "Apply & Watch";
  }
});

document.getElementById("restore-btn").addEventListener("click", async () => {
  const btn = document.getElementById("restore-btn");
  btn.disabled = true;
  try {
    const resp = await fetch("/api/restore", { method: "POST" });
    const res = await resp.json();
    if (!resp.ok) throw new Error(res.error || "Restore failed");
    showToast("Original nous-girl icon restored and watcher paused.");
    await refreshStatus();
  } catch (err) {
    showToast(err.message, false);
  } finally {
    btn.disabled = false;
  }
});

refreshStatus().catch((err) => showToast(err.message, false));
</script>
</body>
</html>
"""


def start_gui_server(
    *,
    port: int = 0,
    open_browser: bool = True,
    keep_open: bool = False,
) -> tuple[ThreadingHTTPServer, str]:
    """Start the local GUI HTTP server on ``127.0.0.1`` and return ``(server, url)``."""
    upload_dir = Path(tempfile.mkdtemp(prefix="hermes-icon-gui-"))
    uploaded_tokens: dict[str, Path] = {}
    upload_lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            return

        def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length > 0 else b"{}"
            return json.loads(raw.decode("utf-8"))

        def do_GET(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path == "/":
                body = HTML_PAGE.encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            if parsed.path == "/api/status":
                cfg = load_config()
                self._send_json(
                    {
                        "config": cfg.to_dict(),
                        "surfaces": inspect_surfaces(),
                        "watcher": watcher_status(),
                        "presets": [
                            {
                                "id": pid,
                                "name": PRESETS[pid].name,
                                "tagline": PRESETS[pid].tagline,
                                "description": PRESETS[pid].description,
                            }
                            for pid in PRESET_ORDER
                        ],
                    }
                )
                return

            if parsed.path == "/api/preview":
                qs = urllib.parse.parse_qs(parsed.query)
                cur_cfg = load_config()
                mode = qs.get("mode", ["preset"])[0]
                preset = qs.get("preset", [cur_cfg.preset])[0]
                appearance = qs.get("appearance", ["light"])[0]
                bg_light = normalize_hex_color(qs.get("bg_light", [cur_cfg.bg_light])[0], DEFAULT_BG_LIGHT)
                bg_dark = normalize_hex_color(qs.get("bg_dark", [cur_cfg.bg_dark])[0], DEFAULT_BG_DARK)
                scale = float(qs.get("scale", [str(cur_cfg.scale)])[0])
                full_bleed = qs.get("full_bleed", ["0"])[0] == "1"
                custom_token = qs.get("custom_token", [None])[0]
                custom_dark_token = qs.get("custom_dark_token", [None])[0]

                custom_path = cur_cfg.custom_path
                if custom_token and custom_token in uploaded_tokens:
                    custom_path = str(uploaded_tokens[custom_token])
                custom_dark_path = cur_cfg.custom_dark_path
                if custom_dark_token and custom_dark_token in uploaded_tokens:
                    custom_dark_path = str(uploaded_tokens[custom_dark_token])

                try:
                    preview_cfg = IconConfig(
                        mode=mode,
                        preset=preset,
                        custom_path=custom_path,
                        custom_dark_path=custom_dark_path,
                        scale=scale,
                        full_bleed=True if full_bleed else None,
                        bg_light=bg_light,
                        bg_dark=bg_dark,
                        fg_light=DEFAULT_FG_LIGHT,
                        fg_dark=DEFAULT_FG_DARK,
                    )
                    img = IconRenderer(preview_cfg).render_squircle(
                        256, dark=(appearance == "dark"), mac_grid=False
                    )
                    buf = io.BytesIO()
                    img.save(buf, "PNG")
                    body = buf.getvalue()
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "image/png")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                except Exception as exc:
                    self._send_json({"error": str(exc)}, status=400)
                return

            self._send_json({"error": "Not found"}, status=404)

        def do_POST(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path == "/api/upload":
                try:
                    payload = self._read_json()
                    filename = Path(payload.get("filename", "icon.png")).name
                    ext = Path(filename).suffix.lower()
                    if ext not in (".svg", ".png", ".icns", ".ico", ".jpg", ".jpeg", ".webp"):
                        raise ValueError(f"Unsupported extension {ext!r}")
                    raw = base64.b64decode(payload["data_base64"])
                    with upload_lock:
                        token = f"u{len(uploaded_tokens) + 1}{ext}"
                        dst = upload_dir / token
                        dst.write_bytes(raw)
                        uploaded_tokens[token] = dst
                    self._send_json({"token": token, "filename": filename})
                except Exception as exc:
                    self._send_json({"error": str(exc)}, status=400)
                return

            if parsed.path == "/api/apply":
                try:
                    payload = self._read_json()
                    cur_cfg = load_config()
                    mode = payload.get("mode", "preset")
                    preset = payload.get("preset", cur_cfg.preset)
                    bg_light = normalize_hex_color(payload.get("bg_light", cur_cfg.bg_light), DEFAULT_BG_LIGHT)
                    bg_dark = normalize_hex_color(payload.get("bg_dark", cur_cfg.bg_dark), DEFAULT_BG_DARK)
                    scale = float(payload.get("scale", cur_cfg.scale))
                    full_bleed = bool(payload.get("full_bleed", False))
                    custom_token = payload.get("custom_token")
                    custom_dark_token = payload.get("custom_dark_token")

                    custom_path = cur_cfg.custom_path
                    if custom_token and custom_token in uploaded_tokens:
                        CUSTOM_ASSETS_DIR.mkdir(parents=True, exist_ok=True)
                        src = uploaded_tokens[custom_token]
                        perm = CUSTOM_ASSETS_DIR / f"custom_light{src.suffix.lower()}"
                        perm.write_bytes(src.read_bytes())
                        custom_path = str(perm)

                    custom_dark_path = cur_cfg.custom_dark_path
                    if custom_dark_token and custom_dark_token in uploaded_tokens:
                        CUSTOM_ASSETS_DIR.mkdir(parents=True, exist_ok=True)
                        src_d = uploaded_tokens[custom_dark_token]
                        perm_d = CUSTOM_ASSETS_DIR / f"custom_dark{src_d.suffix.lower()}"
                        perm_d.write_bytes(src_d.read_bytes())
                        custom_dark_path = str(perm_d)

                    new_cfg = IconConfig(
                        mode=mode,
                        preset=preset,
                        custom_path=custom_path if mode == "custom" else None,
                        custom_dark_path=custom_dark_path if mode == "custom" else None,
                        scale=scale,
                        full_bleed=True if full_bleed else None,
                        bg_light=bg_light,
                        bg_dark=bg_dark,
                    )
                    t0 = time.monotonic()
                    apply_res = apply_icon(new_cfg)
                    watch_res = install_watcher()
                    elapsed_s = round(time.monotonic() - t0, 2)
                    auto_quit = not keep_open
                    self._send_json({
                        "apply": apply_res,
                        "watcher": watch_res,
                        "elapsed_s": elapsed_s,
                        "auto_quit": auto_quit,
                    })
                    if auto_quit:
                        timer = threading.Timer(0.5, server.shutdown)
                        timer.daemon = True
                        timer.start()
                except Exception as exc:
                    self._send_json({"error": str(exc)}, status=400)
                return

            if parsed.path == "/api/restore":
                try:
                    cfg = load_config()
                    cfg.watch_paused = True
                    save_config(cfg)
                    res = restore_original_icons()
                    self._send_json({"restored": res})
                except Exception as exc:
                    self._send_json({"error": str(exc)}, status=400)
                return

            self._send_json({"error": "Not found"}, status=404)

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    bound_port = server.server_address[1]
    url = f"http://127.0.0.1:{bound_port}/"
    if open_browser:
        if sys.platform == "darwin":
            subprocess.Popen(["/usr/bin/open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif sys.platform == "win32":
            try:
                os.startfile(url)  # type: ignore[attr-defined]
            except Exception:
                subprocess.Popen(["cmd", "/c", "start", "", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return server, url


def run_gui(*, port: int = 0, open_browser: bool = True, keep_open: bool = False) -> int:
    server, url = start_gui_server(port=port, open_browser=open_browser, keep_open=keep_open)
    print(f"Hermes Icon GUI running at {url}")
    print("Select an icon and click 'Apply & Watch' (auto-exits on apply), or press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down GUI server.")
    finally:
        server.shutdown()
        server.server_close()
    return 0
