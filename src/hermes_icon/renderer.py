"""Icon rendering engine for hermes-icon.

Handles preset vector SVGs and custom (.svg, .png, .icns, .jpg, .webp) assets,
runs generate_icons.py for compatibility, renders clean undistorted centered
versions of all 99 repo targets, and verifies generate_icons.py --check passes.
"""

from __future__ import annotations

import base64
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import resvg_py
from PIL import Image, ImageChops, ImageOps

from .config import (
    DEFAULT_BG_DARK,
    DEFAULT_BG_LIGHT,
    DEFAULT_FG_DARK,
    DEFAULT_FG_LIGHT,
    GENERATE_ICONS_PY,
    HERMES_REPO,
    IconConfig,
)
from .presets import ASSETS_DIR, PRESETS, VIEWBOX, build_preset_svg, resolve_preset_id

ICON_CANVAS = 1024
MAC_TILE_OFFSET = 100
MAC_TILE_SIZE = 824
SQUIRCLE_RX = 245.0
MAC_SQUIRCLE_RX = 185.4

_PRESET_BBOX_CACHE: dict[str, tuple[float, float, float, float]] = {}


def _load_generate_icons_module():
    spec = importlib.util.spec_from_file_location("_hermes_generate_icons", str(GENERATE_ICONS_PY))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _save_png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    rgba = img if img.mode == "RGBA" else img.convert("RGBA")
    rgba.save(buf, "PNG", compress_level=3)
    return buf.getvalue()


def _save_ico_bytes(img: Image.Image, sizes: list[int]) -> bytes:
    buf = io.BytesIO()
    max_s = max(sizes)
    base = img.resize((max_s, max_s), Image.LANCZOS) if img.size != (max_s, max_s) else img
    base.save(buf, format="ICO", sizes=[(s, s) for s in sizes])
    return buf.getvalue()


def _save_icns_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    base = img.resize((1024, 1024), Image.LANCZOS) if img.size != (1024, 1024) else img
    frames = [base.resize((s, s), Image.LANCZOS) for s in (16, 32, 64, 128, 256, 512, 1024)]
    base.save(buf, format="ICNS", append_images=frames[1:])
    return buf.getvalue()


def _squircle_mask(size: int, mac_grid: bool = False) -> Image.Image:
    if mac_grid:
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024">'
            f'<rect x="{MAC_TILE_OFFSET}" y="{MAC_TILE_OFFSET}" '
            f'width="{MAC_TILE_SIZE}" height="{MAC_TILE_SIZE}" '
            f'rx="{MAC_SQUIRCLE_RX}" fill="#ffffff"/></svg>'
        )
    else:
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024">'
            f'<rect x="0" y="0" width="1024" height="1024" rx="{SQUIRCLE_RX}" fill="#ffffff"/></svg>'
        )
    data = resvg_py.svg_to_bytes(svg_string=svg, width=size, height=size)
    return Image.open(io.BytesIO(data)).convert("RGBA").getchannel("A")


def _squircle_plate(size: int, bg_hex: str, mac_grid: bool = False) -> Image.Image:
    if mac_grid:
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024">'
            f'<rect x="{MAC_TILE_OFFSET}" y="{MAC_TILE_OFFSET}" '
            f'width="{MAC_TILE_SIZE}" height="{MAC_TILE_SIZE}" '
            f'rx="{MAC_SQUIRCLE_RX}" fill="{bg_hex}"/></svg>'
        )
    else:
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024">'
            f'<rect x="0" y="0" width="1024" height="1024" rx="{SQUIRCLE_RX}" fill="{bg_hex}"/></svg>'
        )
    data = resvg_py.svg_to_bytes(svg_string=svg, width=size, height=size)
    return Image.open(io.BytesIO(data)).convert("RGBA")


def _detect_full_bleed(img: Image.Image, ext: str) -> bool:
    """Detect whether a custom raster/icns input is already an opaque square or full-tile squircle."""
    rgba = img.convert("RGBA")
    w, h = rgba.size
    alpha = rgba.getchannel("A")
    corners = [
        alpha.getpixel((0, 0)),
        alpha.getpixel((w - 1, 0)),
        alpha.getpixel((0, h - 1)),
        alpha.getpixel((w - 1, h - 1)),
    ]
    if all(c >= 240 for c in corners):
        return True
    if ext == ".icns":
        bbox = alpha.point(lambda v: 255 if v > 8 else 0).getbbox()
        if bbox:
            cropped = alpha.crop(bbox)
            cw, ch = cropped.size
            if cw > 0 and ch > 0:
                mids = [
                    cropped.getpixel((cw // 2, min(ch - 1, 4))),
                    cropped.getpixel((cw // 2, max(0, ch - 5))),
                    cropped.getpixel((min(cw - 1, 4), ch // 2)),
                    cropped.getpixel((max(0, cw - 5), ch // 2)),
                    cropped.getpixel((cw // 2, ch // 2)),
                ]
                if all(m >= 240 for m in mids):
                    return True
    return False


def _load_custom_image(path: Path) -> tuple[Image.Image, str, str | None]:
    """Load .svg/.png/.jpg/.webp/.icns as (1024-scale RGBA Image, ext, raw_svg_or_None)."""
    if not path.exists():
        raise FileNotFoundError(f"Custom icon not found: {path}")
    ext = path.suffix.lower()
    if ext == ".svg":
        svg_text = path.read_text(encoding="utf-8-sig")
        data = resvg_py.svg_to_bytes(svg_string=svg_text, width=1024, height=1024)
        img = Image.open(io.BytesIO(data)).convert("RGBA")
        return img, ext, svg_text
    if ext in (".png", ".jpg", ".jpeg", ".webp", ".icns"):
        with Image.open(path) as im:
            img = im.convert("RGBA")
        return img, ext, None
    raise ValueError(f"Unsupported custom icon extension {ext!r} (expected .svg, .png, .icns, .jpg, .webp)")


def _trim_alpha(img: Image.Image) -> Image.Image:
    rgba = img.convert("RGBA")
    bbox = rgba.getchannel("A").point(lambda v: 255 if v > 0 else 0).getbbox()
    if bbox:
        return rgba.crop(bbox)
    return rgba


def _fit_centered(img: Image.Image, box_w: int, box_h: int) -> Image.Image:
    """Scale ``img`` proportionally to fit inside ``(box_w, box_h)``."""
    iw, ih = img.size
    if iw == 0 or ih == 0:
        return Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
    scale = min(box_w / iw, box_h / ih)
    nw = max(1, round(iw * scale))
    nh = max(1, round(ih * scale))
    return img.resize((nw, nh), Image.LANCZOS)


def _cover_crop(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    return ImageOps.fit(img.convert("RGBA"), (target_w, target_h), method=Image.LANCZOS)


def _compose_squircle_from_image(
    fg_img: Image.Image,
    size: int,
    bg_hex: str,
    *,
    mac_grid: bool = False,
    scale: float = 0.78,
    full_bleed: bool = False,
) -> Image.Image:
    if full_bleed:
        trimmed = _trim_alpha(fg_img)
        if mac_grid:
            tile_size = round(size * MAC_TILE_SIZE / 1024.0)
            offset = round(size * MAC_TILE_OFFSET / 1024.0)
            fitted = _cover_crop(trimmed, tile_size, tile_size)
            canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            canvas.paste(fitted, (offset, offset))
        else:
            canvas = _cover_crop(trimmed, size, size)
        mask = _squircle_mask(size, mac_grid=mac_grid)
        # Preserve alpha inside the tile while clipping outside the squircle
        alpha = ImageChops.darker(canvas.getchannel("A"), mask)
        canvas.putalpha(alpha)
        return canvas

    plate = _squircle_plate(size, bg_hex, mac_grid=mac_grid)
    trimmed = _trim_alpha(fg_img)
    tile_side = (size * MAC_TILE_SIZE / 1024.0) if mac_grid else float(size)
    inner_box = max(1, round(tile_side * scale))
    fitted = _fit_centered(trimmed, inner_box, inner_box)
    ox = (size - fitted.width) // 2
    oy = (size - fitted.height) // 2
    plate.alpha_composite(fitted, (ox, oy))
    return plate


def _compose_bottom_anchored_squircle(
    fg_img: Image.Image,
    size: int,
    bg_hex: str,
    *,
    mac_grid: bool = False,
    scale: float = 0.78,
) -> Image.Image:
    """Composite a portrait cutout flush with the bottom of the squircle and clip corners."""
    plate = _squircle_plate(size, bg_hex, mac_grid=mac_grid)
    trimmed = _trim_alpha(fg_img)
    tile_side = (size * MAC_TILE_SIZE / 1024.0) if mac_grid else float(size)
    # Portrait fills ~90% of tile height at default scale=0.78 so shoulders sit flush at bottom
    eff_scale = min(0.95, max(0.45, scale * (0.90 / 0.78)))
    box = max(1, round(tile_side * eff_scale))
    fitted = _fit_centered(trimmed, box, box)
    ox = (size - fitted.width) // 2
    tile_bottom = round(size * (MAC_TILE_OFFSET + MAC_TILE_SIZE) / 1024.0) if mac_grid else size
    oy = tile_bottom - fitted.height
    fg_layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    fg_layer.alpha_composite(fitted, (ox, oy))
    mask = _squircle_mask(size, mac_grid=mac_grid)
    fg_layer.putalpha(ImageChops.darker(fg_layer.getchannel("A"), mask))
    plate.alpha_composite(fg_layer)
    return plate


def _trace_alpha_to_mlz_svg(img: Image.Image, fill: str) -> str:
    """Convert an RGBA image into a valid single-<path> M/L/Z SVG in 5487.0615 viewBox.

    Used for custom raster/multi-color SVGs so assets/nous-girl-{black,white}.svg
    always pass generate_icons.py's strict M/L/C/Z parser and --check validation.
    """
    grid = 96
    trimmed = _trim_alpha(img)
    # Place centered inside a 96x96 padded grid (10% margin)
    inner = 76
    fitted = _fit_centered(trimmed, inner, inner)
    canvas = Image.new("RGBA", (grid, grid), (0, 0, 0, 0))
    canvas.alpha_composite(fitted, ((grid - fitted.width) // 2, (grid - fitted.height) // 2))
    alpha = canvas.getchannel("A")
    px = alpha.load()

    cell = VIEWBOX / grid
    parts: list[str] = []
    for y in range(grid):
        x = 0
        while x < grid:
            if px[x, y] >= 64:
                x0 = x
                while x < grid and px[x, y] >= 64:
                    x += 1
                rx0 = x0 * cell
                rx1 = x * cell
                ry0 = y * cell
                ry1 = (y + 1) * cell
                parts.append(
                    f"M {rx0:.2f} {ry0:.2f} L {rx1:.2f} {ry0:.2f} "
                    f"L {rx1:.2f} {ry1:.2f} L {rx0:.2f} {ry1:.2f} Z"
                )
            else:
                x += 1

    if not parts:
        # Fallback tiny centered square
        c0, c1 = VIEWBOX * 0.25, VIEWBOX * 0.75
        parts.append(f"M {c0:.2f} {c0:.2f} L {c1:.2f} {c0:.2f} L {c1:.2f} {c1:.2f} L {c0:.2f} {c1:.2f} Z")

    d = " ".join(parts)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {VIEWBOX} {VIEWBOX}" width="{VIEWBOX}" height="{VIEWBOX}">\n'
        f'  <path d="{d}" fill="{fill}"/>\n'
        f"</svg>\n"
    )


def _preset_bbox(preset_id: str) -> tuple[float, float, float, float]:
    """Cached alpha bbox of a preset in VIEWBOX coordinates."""
    if preset_id not in _PRESET_BBOX_CACHE:
        raw_svg = build_preset_svg(preset_id, "#000000")
        data = resvg_py.svg_to_bytes(svg_string=raw_svg, width=512, height=512)
        im = Image.open(io.BytesIO(data)).convert("RGBA")
        bbox = im.getchannel("A").point(lambda v: 255 if v > 0 else 0).getbbox() or (0, 0, 512, 512)
        s = VIEWBOX / 512.0
        _PRESET_BBOX_CACHE[preset_id] = (
            bbox[0] * s,
            bbox[1] * s,
            (bbox[2] - bbox[0]) * s,
            (bbox[3] - bbox[1]) * s,
        )
    return _PRESET_BBOX_CACHE[preset_id]


def _preset_master_svg(preset_id: str, bg_hex: str, fg_hex: str, *, mac_grid: bool = False, scale: float = 0.78) -> str:
    """Pure vector centered squircle master SVG for a preset."""
    d = PRESETS[preset_id].build_path()
    bx, by, bw, bh = _preset_bbox(preset_id)

    if mac_grid:
        tile_rect = (
            f'<rect x="{MAC_TILE_OFFSET}" y="{MAC_TILE_OFFSET}" '
            f'width="{MAC_TILE_SIZE}" height="{MAC_TILE_SIZE}" '
            f'rx="{MAC_SQUIRCLE_RX}" fill="{bg_hex}"/>'
        )
        tile_side = float(MAC_TILE_SIZE)
    else:
        tile_rect = f'<rect x="0" y="0" width="1024" height="1024" rx="{SQUIRCLE_RX}" fill="{bg_hex}"/>'
        tile_side = 1024.0

    box_size = tile_side * scale
    box_x = (1024.0 - box_size) / 2.0
    box_y = (1024.0 - box_size) / 2.0
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024">\n'
        f'  <defs><clipPath id="icon-silhouette">{tile_rect}</clipPath></defs>\n'
        f'  {tile_rect}\n'
        f'  <g clip-path="url(#icon-silhouette)">\n'
        f'    <svg x="{box_x:.2f}" y="{box_y:.2f}" width="{box_size:.2f}" height="{box_size:.2f}" '
        f'viewBox="{bx:.2f} {by:.2f} {bw:.2f} {bh:.2f}" preserveAspectRatio="xMidYMid meet">\n'
        f'      <path d="{d}" fill="{fg_hex}"/>\n'
        f'    </svg>\n'
        f'  </g>\n'
        f'</svg>\n'
    )


def _raster_master_svg(img: Image.Image, size: int = 1024) -> str:
    """Embed a rendered 1024x1024 squircle PNG inside an SVG wrapper (for icon-master.svg / favicon.svg)."""
    resized = img.resize((size, size), Image.LANCZOS) if img.size != (size, size) else img
    b64 = base64.b64encode(_save_png_bytes(resized)).decode("ascii")
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" '
        f'width="{size}" height="{size}">\n'
        f'  <image href="data:image/png;base64,{b64}" width="{size}" height="{size}"/>\n'
        f'</svg>\n'
    )


class IconRenderer:
    """Renders any IconConfig (preset or custom) to all repo & desktop targets."""

    def __init__(self, cfg: IconConfig):
        self.cfg = cfg
        self.is_custom = cfg.mode == "custom"
        self.scale = max(0.35, min(1.0, float(cfg.scale or 0.78)))
        self.bg_light = cfg.bg_light or DEFAULT_BG_LIGHT
        self.bg_dark = cfg.bg_dark or DEFAULT_BG_DARK
        self.fg_light = cfg.fg_light or DEFAULT_FG_LIGHT
        self.fg_dark = cfg.fg_dark or DEFAULT_FG_DARK

        self._light_fg_img: Image.Image | None = None
        self._dark_fg_img: Image.Image | None = None
        self._preset_id: str | None = None
        self._preset_img: Image.Image | None = None
        self._bottom_anchored: bool = False
        self._full_bleed: bool = False
        self._svg_light_text: str | None = None
        self._svg_dark_text: str | None = None
        self._squircle_1024_cache: dict[tuple[bool, bool], Image.Image] = {}
        self._fg_1024_cache: dict[bool, Image.Image] = {}
        self._target_bytes_cache: dict[tuple[str, str], bytes] = {}

        if self.is_custom:
            if not cfg.custom_path:
                raise ValueError("Custom mode requires custom_path")
            light_img, ext, raw_svg = _load_custom_image(Path(cfg.custom_path))
            self._light_fg_img = light_img
            self._svg_light_text = raw_svg
            if cfg.custom_dark_path:
                dark_img, _, raw_dark_svg = _load_custom_image(Path(cfg.custom_dark_path))
                self._dark_fg_img = dark_img
                self._svg_dark_text = raw_dark_svg
            else:
                self._dark_fg_img = light_img
                self._svg_dark_text = raw_svg
            self._full_bleed = cfg.full_bleed if cfg.full_bleed is not None else _detect_full_bleed(light_img, ext)
        else:
            pid = resolve_preset_id(cfg.preset)
            if pid not in PRESETS:
                raise ValueError(f"Unknown preset: {cfg.preset!r}")
            self._preset_id = pid
            preset_obj = PRESETS[pid]
            self._bottom_anchored = preset_obj.bottom_anchored
            if preset_obj.image_asset:
                with Image.open(ASSETS_DIR / preset_obj.image_asset) as im:
                    self._preset_img = im.convert("RGBA")
            self._full_bleed = False

    def source_svgs(self) -> tuple[str, str]:
        """Return (nous-girl-black.svg, nous-girl-white.svg) compatible with generate_icons.py."""
        if not self.is_custom:
            assert self._preset_id is not None
            return (
                build_preset_svg(self._preset_id, self.fg_light),
                build_preset_svg(self._preset_id, self.fg_dark),
            )
        assert self._light_fg_img is not None and self._dark_fg_img is not None
        return (
            _trace_alpha_to_mlz_svg(self._light_fg_img, self.fg_light),
            _trace_alpha_to_mlz_svg(self._dark_fg_img, self.fg_dark),
        )

    def render_foreground(self, size: int, *, dark: bool = False) -> Image.Image:
        """Render the standalone emblem/artwork on transparency (``size``x``size``)."""
        if dark not in self._fg_1024_cache:
            if not self.is_custom:
                if self._preset_img is not None:
                    img = self._preset_img
                else:
                    assert self._preset_id is not None
                    fg = self.fg_dark if dark else self.fg_light
                    svg = build_preset_svg(self._preset_id, fg)
                    data = resvg_py.svg_to_bytes(svg_string=svg, width=ICON_CANVAS, height=ICON_CANVAS)
                    img = Image.open(io.BytesIO(data)).convert("RGBA")
            else:
                raw_svg = self._svg_dark_text if dark else self._svg_light_text
                if raw_svg is not None:
                    data = resvg_py.svg_to_bytes(svg_string=raw_svg, width=ICON_CANVAS, height=ICON_CANVAS)
                    img = Image.open(io.BytesIO(data)).convert("RGBA")
                else:
                    img = self._dark_fg_img if dark else self._light_fg_img
                    assert img is not None
            trimmed = _trim_alpha(img)
            fitted = _fit_centered(trimmed, ICON_CANVAS, ICON_CANVAS)
            canvas = Image.new("RGBA", (ICON_CANVAS, ICON_CANVAS), (0, 0, 0, 0))
            oy = (ICON_CANVAS - fitted.height) if self._bottom_anchored else ((ICON_CANVAS - fitted.height) // 2)
            canvas.alpha_composite(fitted, ((ICON_CANVAS - fitted.width) // 2, oy))
            self._fg_1024_cache[dark] = canvas

        base = self._fg_1024_cache[dark]
        if size == ICON_CANVAS:
            return base.copy()
        return base.resize((size, size), Image.LANCZOS)

    def render_squircle(self, size: int, *, dark: bool = False, mac_grid: bool = False) -> Image.Image:
        """Render clean, centered, undistorted squircle tile at ``size``x``size``."""
        key = (bool(dark), bool(mac_grid))
        if key not in self._squircle_1024_cache:
            bg = self.bg_dark if dark else self.bg_light
            if not self.is_custom:
                if self._preset_img is not None:
                    if self._bottom_anchored:
                        self._squircle_1024_cache[key] = _compose_bottom_anchored_squircle(
                            self._preset_img,
                            ICON_CANVAS,
                            bg,
                            mac_grid=mac_grid,
                            scale=self.scale,
                        )
                    else:
                        self._squircle_1024_cache[key] = _compose_squircle_from_image(
                            self._preset_img,
                            ICON_CANVAS,
                            bg,
                            mac_grid=mac_grid,
                            scale=self.scale,
                            full_bleed=False,
                        )
                else:
                    assert self._preset_id is not None
                    fg = self.fg_dark if dark else self.fg_light
                    master = _preset_master_svg(self._preset_id, bg, fg, mac_grid=mac_grid, scale=self.scale)
                    data = resvg_py.svg_to_bytes(svg_string=master, width=ICON_CANVAS, height=ICON_CANVAS)
                    self._squircle_1024_cache[key] = Image.open(io.BytesIO(data)).convert("RGBA")
            else:
                raw_svg = self._svg_dark_text if dark else self._svg_light_text
                if raw_svg is not None:
                    data = resvg_py.svg_to_bytes(svg_string=raw_svg, width=ICON_CANVAS, height=ICON_CANVAS)
                    fg_img = Image.open(io.BytesIO(data)).convert("RGBA")
                else:
                    fg_img = self._dark_fg_img if dark else self._light_fg_img
                    assert fg_img is not None
                self._squircle_1024_cache[key] = _compose_squircle_from_image(
                    fg_img,
                    ICON_CANVAS,
                    bg,
                    mac_grid=mac_grid,
                    scale=self.scale,
                    full_bleed=self._full_bleed,
                )

        base = self._squircle_1024_cache[key]
        if size == ICON_CANVAS:
            return base.copy()
        return base.resize((size, size), Image.LANCZOS)

    def render_icon_art(self, dark: bool = False) -> Image.Image:
        """1024x1024 layer for macOS 26 Icon Composer (art-light.png / art-dark.png)."""
        if self._full_bleed and self.is_custom:
            fg_img = self._dark_fg_img if dark else self._light_fg_img
            assert fg_img is not None
            return _cover_crop(_trim_alpha(fg_img), ICON_CANVAS, ICON_CANVAS)

        # Icon Composer places the 1024 layer onto the 824 grid itself, so
        # scale inside 1024 canvas matches mac_grid squircle proportions.
        fg = self.render_foreground(ICON_CANVAS, dark=dark)
        trimmed = _trim_alpha(fg)
        if self._bottom_anchored:
            eff_scale = min(0.95, max(0.45, self.scale * (0.90 / 0.78)))
            box = max(1, round(ICON_CANVAS * eff_scale))
            fitted = _fit_centered(trimmed, box, box)
            canvas = Image.new("RGBA", (ICON_CANVAS, ICON_CANVAS), (0, 0, 0, 0))
            canvas.alpha_composite(fitted, ((ICON_CANVAS - fitted.width) // 2, ICON_CANVAS - fitted.height))
            return canvas

        box = max(1, round(ICON_CANVAS * self.scale))
        fitted = _fit_centered(trimmed, box, box)
        canvas = Image.new("RGBA", (ICON_CANVAS, ICON_CANVAS), (0, 0, 0, 0))
        canvas.alpha_composite(fitted, ((ICON_CANVAS - fitted.width) // 2, (ICON_CANVAS - fitted.height) // 2))
        return canvas

    def render_icon_mono(self) -> Image.Image:
        """1024x1024 Clear/Tinted frosted glass material for Icon Composer."""
        art = self.render_icon_art(dark=False)
        if not self.is_custom and self._preset_img is None:
            alpha = art.getchannel("A")
            out = Image.new("RGBA", (ICON_CANVAS, ICON_CANVAS), (255, 255, 255, 0))
            out.putalpha(alpha)
            return out

        # For full-color raster/preset artwork: convert luminance + alpha to translucent glass material
        luma = art.convert("L")
        alpha = art.getchannel("A")
        if self._full_bleed or self._preset_img is not None:
            glass_alpha = ImageChops.multiply(alpha, luma.point(lambda v: max(55, min(255, v))))
        else:
            glass_alpha = alpha
        out = Image.new("RGBA", (ICON_CANVAS, ICON_CANVAS), (242, 242, 247, 0))
        out.putalpha(glass_alpha)
        return out

    def render_icon_manifest(self) -> str:
        """Icon Composer icon.json using configured light & dark fill colors."""
        def icon_color(hex_color: str) -> str:
            val = hex_color.lstrip("#")
            r, g, b = (int(val[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
            return f"srgb:{r:.5f},{g:.5f},{b:.5f},1.00000"

        manifest = {
            "fill-specializations": [
                {"value": {"solid": icon_color(self.bg_light)}},
                {"appearance": "dark", "value": {"solid": icon_color(self.bg_dark)}},
            ],
            "groups": [{
                "lighting": "individual",
                "specular": False,
                "translucency": {"enabled": False, "value": 0},
                "shadow": {"kind": "none", "opacity": 0},
                "blur-material": None,
                "layers": [
                    {
                        "name": "art",
                        "image-name-specializations": [
                            {"value": "art-light.png"},
                            {"appearance": "dark", "value": "art-dark.png"},
                        ],
                        "glass": False,
                        "hidden-specializations": [
                            {"value": False},
                            {"appearance": "tinted", "value": True},
                        ],
                    },
                    {
                        "name": "mono",
                        "image-name": "mono.png",
                        "glass": True,
                        "hidden-specializations": [
                            {"value": True},
                            {"appearance": "tinted", "value": False},
                        ],
                    },
                ],
            }],
            "supported-platforms": {"squares": "shared"},
        }
        return json.dumps(manifest, indent=2) + "\n"

    def render_master_svg(self, *, dark: bool = False) -> str:
        if not self.is_custom and self._preset_img is None:
            assert self._preset_id is not None
            bg = self.bg_dark if dark else self.bg_light
            fg = self.fg_dark if dark else self.fg_light
            return _preset_master_svg(self._preset_id, bg, fg, mac_grid=False, scale=self.scale)
        return _raster_master_svg(self.render_squircle(1024, dark=dark, mac_grid=False), 1024)

    def render_target_bytes(self, rel: str, kind: str, arg: Any, dmg_png_path: Path) -> bytes:
        cache_key = (kind, repr(arg))
        if kind != "icns_from_png" and cache_key in self._target_bytes_cache:
            return self._target_bytes_cache[cache_key]
        out = self._render_target_bytes_uncached(rel, kind, arg, dmg_png_path)
        if kind != "icns_from_png":
            self._target_bytes_cache[cache_key] = out
        return out

    def _render_target_bytes_uncached(self, rel: str, kind: str, arg: Any, dmg_png_path: Path) -> bytes:
        if kind in ("svg", "svg_copy"):
            return self.render_master_svg(dark=False).encode("utf-8")
        if kind == "svg_dark":
            return self.render_master_svg(dark=True).encode("utf-8")
        if kind == "icon_manifest":
            return self.render_icon_manifest().encode("utf-8")
        if kind == "png":
            return _save_png_bytes(self.render_squircle(int(arg), dark=False, mac_grid=False))
        if kind == "png_mac":
            return _save_png_bytes(self.render_squircle(int(arg), dark=False, mac_grid=True))
        if kind == "png_dark":
            return _save_png_bytes(self.render_squircle(int(arg), dark=True, mac_grid=False))
        if kind == "png_white":
            sq = self.render_squircle(int(arg), dark=False, mac_grid=False)
            bg = Image.new("RGBA", sq.size, self.bg_light)
            bg.alpha_composite(sq)
            buf = io.BytesIO()
            bg.convert("RGB").save(buf, "PNG", optimize=True)
            return buf.getvalue()
        if kind == "png_dark_white":
            sq = self.render_squircle(int(arg), dark=True, mac_grid=False)
            bg = Image.new("RGBA", sq.size, self.bg_dark)
            bg.alpha_composite(sq)
            buf = io.BytesIO()
            bg.convert("RGB").save(buf, "PNG", optimize=True)
            return buf.getvalue()
        if kind == "girl_light":
            return _save_png_bytes(self.render_squircle(int(arg), dark=False, mac_grid=False))
        if kind == "girl_dark":
            return _save_png_bytes(self.render_squircle(int(arg), dark=True, mac_grid=False))
        if kind == "icon_art":
            return _save_png_bytes(self.render_icon_art(dark=(arg == "white")))
        if kind == "icon_mono":
            return _save_png_bytes(self.render_icon_mono())
        if kind == "ico":
            sizes = [int(s) for s in arg]
            return _save_ico_bytes(self.render_squircle(max(sizes), dark=False, mac_grid=False), sizes)
        if kind == "ico_dark":
            sizes = [int(s) for s in arg]
            return _save_ico_bytes(self.render_squircle(max(sizes), dark=True, mac_grid=False), sizes)
        if kind == "icns":
            return _save_icns_bytes(self.render_squircle(1024, dark=False, mac_grid=True))
        if kind == "icns_dark":
            return _save_icns_bytes(self.render_squircle(1024, dark=True, mac_grid=True))
        if kind == "icns_from_png":
            img = Image.open(dmg_png_path).convert("RGBA")
            return _save_icns_bytes(img)
        if kind == "wide":
            w, h, tile = (int(x) for x in arg)
            canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            sq = self.render_squircle(tile, dark=False, mac_grid=False)
            canvas.alpha_composite(sq, ((w - sq.width) // 2, (h - sq.height) // 2))
            return _save_png_bytes(canvas)
        if kind in ("logo", "logo_dark"):
            dark = kind == "logo_dark"
            W, H = 1772, 1799
            fg = self.render_foreground(W, dark=dark)
            canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            canvas.alpha_composite(fg, ((W - fg.width) // 2, (H - fg.height) // 2))
            return _save_png_bytes(canvas)
        raise ValueError(f"Unsupported target kind: {kind!r}")


def apply_to_repo(
    cfg: IconConfig,
    repo: Path = HERMES_REPO,
    *,
    run_upstream_generator: bool = False,
    run_upstream_check: bool = False,
) -> dict[str, Any]:
    """Write source SVGs, render clean centered targets, and optionally run generate_icons.py."""
    renderer = IconRenderer(cfg)
    assets_dir = repo / "assets"
    black_svg, white_svg = renderer.source_svgs()
    (assets_dir / "nous-girl-black.svg").write_text(black_svg, encoding="utf-8")
    (assets_dir / "nous-girl-white.svg").write_text(white_svg, encoding="utf-8")

    # Optional upstream generate_icons.py run (skipped by default for fast interactive apply)
    if run_upstream_generator:
        env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME")}
        proc = subprocess.run(
            [sys.executable, "-I", str(GENERATE_ICONS_PY), "--source", str(repo), "--out", str(repo)],
            capture_output=True,
            text=True,
            env=env,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"generate_icons.py failed (rc={proc.returncode}):\n{proc.stdout}\n{proc.stderr}"
            )

    # Render clean, undistorted, centered versions of all 99 targets
    gen_mod = _load_generate_icons_module()
    written = 0
    for rel, kind, arg in gen_mod.TARGETS:
        out_path = repo / rel
        if kind == "icns_from_png":
            # dmg-volume.icns uses assets/dmg-volume.png (unchanged); skip re-encoding if already valid
            if out_path.exists() and out_path.stat().st_size > 0:
                written += 1
                continue
            dmg_src = repo / str(arg)
            if not dmg_src.exists():
                continue
        out_path.parent.mkdir(parents=True, exist_ok=True)
        data = renderer.render_target_bytes(rel, kind, arg, repo / "assets" / "dmg-volume.png")
        out_path.write_bytes(data)
        written += 1

    check_stdout = "skipped (fast apply)"
    if run_upstream_check:
        env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME")}
        check_proc = subprocess.run(
            [sys.executable, "-I", str(GENERATE_ICONS_PY), "--check", "--source", str(repo), "--out", str(repo)],
            capture_output=True,
            text=True,
            env=env,
        )
        if check_proc.returncode != 0:
            raise RuntimeError(
                f"generate_icons.py --check failed (rc={check_proc.returncode}):\n"
                f"{check_proc.stdout}\n{check_proc.stderr}"
            )
        check_stdout = check_proc.stdout.strip()

    return {
        "targets_written": written,
        "check_stdout": check_stdout,
    }
