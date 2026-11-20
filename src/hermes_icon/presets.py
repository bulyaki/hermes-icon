"""Curated geometric vector presets for hermes-icon.

Every preset produces a single ``<path>`` SVG with viewBox ``0 0 5487.0615 5487.0615``
using ONLY explicit absolute ``M``, ``L``, ``C``, ``Z`` path commands and
deterministic ``nonzero`` winding (``ccw=False`` for solid positive fills,
``ccw=True`` for negative-space cutouts) so overlapping subpaths union cleanly
with zero self-intersection holes and remain 100% compatible with
``hermes-agent/scripts/generate_icons.py``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Iterable

VIEWBOX = 5487.0615
CENTER = VIEWBOX / 2.0
KAPPA = 0.5522847498307936


@dataclass(frozen=True)
class Preset:
    id: str
    name: str
    tagline: str
    description: str
    build_path: Callable[[], str]


def _f(v: float) -> str:
    s = f"{v:.2f}"
    if s == "-0.00":
        return "0.00"
    return s


def _pt(x: float, y: float) -> str:
    return f"{_f(x)} {_f(y)}"


def _shoelace_sum(pts: list[tuple[float, float]]) -> float:
    """Shoelace sum in screen coordinates (+Y down): negative => CW, positive => CCW."""
    n = len(pts)
    total = 0.0
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        total += (x2 - x1) * (y2 + y1)
    return total


def _ensure_winding(pts: list[tuple[float, float]], ccw: bool = False) -> list[tuple[float, float]]:
    """Orient polygon vertices deterministically (CW when ccw=False, CCW when ccw=True)."""
    if len(pts) < 3:
        return pts
    s = _shoelace_sum(pts)
    is_ccw = s > 0
    if is_ccw != ccw:
        return list(reversed(pts))
    return pts


def _circle(cx: float, cy: float, r: float, ccw: bool = False) -> str:
    k = r * KAPPA
    if not ccw:
        return (
            f"M {_pt(cx + r, cy)} "
            f"C {_pt(cx + r, cy + k)} {_pt(cx + k, cy + r)} {_pt(cx, cy + r)} "
            f"C {_pt(cx - k, cy + r)} {_pt(cx - r, cy + k)} {_pt(cx - r, cy)} "
            f"C {_pt(cx - r, cy - k)} {_pt(cx - k, cy - r)} {_pt(cx, cy - r)} "
            f"C {_pt(cx + k, cy - r)} {_pt(cx + r, cy - k)} {_pt(cx + r, cy)} Z"
        )
    return (
        f"M {_pt(cx + r, cy)} "
        f"C {_pt(cx + r, cy - k)} {_pt(cx + k, cy - r)} {_pt(cx, cy - r)} "
        f"C {_pt(cx - k, cy - r)} {_pt(cx - r, cy - k)} {_pt(cx - r, cy)} "
        f"C {_pt(cx - r, cy + k)} {_pt(cx - k, cy + r)} {_pt(cx, cy + r)} "
        f"C {_pt(cx + k, cy + r)} {_pt(cx + r, cy + k)} {_pt(cx + r, cy)} Z"
    )


def _rounded_rect(x: float, y: float, w: float, h: float, rx: float, ccw: bool = False) -> str:
    r = min(rx, w / 2.0, h / 2.0)
    k = r * KAPPA
    x0, y0, x1, y1 = x, y, x + w, y + h
    if not ccw:
        return (
            f"M {_pt(x0 + r, y0)} "
            f"L {_pt(x1 - r, y0)} "
            f"C {_pt(x1 - r + k, y0)} {_pt(x1, y0 + r - k)} {_pt(x1, y0 + r)} "
            f"L {_pt(x1, y1 - r)} "
            f"C {_pt(x1, y1 - r + k)} {_pt(x1 - r + k, y1)} {_pt(x1 - r, y1)} "
            f"L {_pt(x0 + r, y1)} "
            f"C {_pt(x0 + r - k, y1)} {_pt(x0, y1 - r + k)} {_pt(x0, y1 - r)} "
            f"L {_pt(x0, y0 + r)} "
            f"C {_pt(x0, y0 + r - k)} {_pt(x0 + r - k, y0)} {_pt(x0 + r, y0)} Z"
        )
    return (
        f"M {_pt(x0 + r, y0)} "
        f"C {_pt(x0 + r - k, y0)} {_pt(x0, y0 + r - k)} {_pt(x0, y0 + r)} "
        f"L {_pt(x0, y1 - r)} "
        f"C {_pt(x0, y1 - r + k)} {_pt(x0 + r - k, y1)} {_pt(x0 + r, y1)} "
        f"L {_pt(x1 - r, y1)} "
        f"C {_pt(x1 - r + k, y1)} {_pt(x1, y1 - r + k)} {_pt(x1, y1 - r)} "
        f"L {_pt(x1, y0 + r)} "
        f"C {_pt(x1, y0 + r - k)} {_pt(x1 - r + k, y0)} {_pt(x1 - r, y0)} "
        f"L {_pt(x0 + r, y0)} Z"
    )


def _polygon(pts: Iterable[tuple[float, float]], ccw: bool = False) -> str:
    items = _ensure_winding(list(pts), ccw=ccw)
    if not items:
        return ""
    parts = [f"M {_pt(items[0][0], items[0][1])}"]
    for x, y in items[1:]:
        parts.append(f"L {_pt(x, y)}")
    parts.append("Z")
    return " ".join(parts)


def _smooth_closed(pts: list[tuple[float, float]], ccw: bool = False) -> str:
    """Closed Catmull-Rom cubic Bezier spline through ``pts`` with deterministic winding."""
    pts = _ensure_winding(pts, ccw=ccw)
    n = len(pts)
    parts = [f"M {_pt(pts[0][0], pts[0][1])}"]
    for i in range(n):
        p0 = pts[(i - 1) % n]
        p1 = pts[i]
        p2 = pts[(i + 1) % n]
        p3 = pts[(i + 2) % n]
        c1 = (p1[0] + (p2[0] - p0[0]) / 6.0, p1[1] + (p2[1] - p0[1]) / 6.0)
        c2 = (p2[0] - (p3[0] - p1[0]) / 6.0, p2[1] - (p3[1] - p1[1]) / 6.0)
        parts.append(f"C {_pt(c1[0], c1[1])} {_pt(c2[0], c2[1])} {_pt(p2[0], p2[1])}")
    parts.append("Z")
    return " ".join(parts)


def _capsule(x1: float, y1: float, x2: float, y2: float, r: float, ccw: bool = False) -> str:
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy)
    if length < 1e-6:
        return _circle(x1, y1, r, ccw=ccw)
    ux, uy = dx / length, dy / length
    # In screen coordinates (+Y down), (uy, -ux) points to the left side of the vector,
    # giving clockwise winding when walking a1 -> a2 -> cap2 -> b2 -> b1 -> cap1.
    nx, ny = (uy, -ux) if not ccw else (-uy, ux)
    k = r * KAPPA
    a1 = (x1 + nx * r, y1 + ny * r)
    a2 = (x2 + nx * r, y2 + ny * r)
    b2 = (x2 - nx * r, y2 - ny * r)
    b1 = (x1 - nx * r, y1 - ny * r)
    return (
        f"M {_pt(*a1)} "
        f"L {_pt(*a2)} "
        f"C {_pt(a2[0] + ux * k, a2[1] + uy * k)} {_pt(x2 + ux * r + nx * k, y2 + uy * r + ny * k)} {_pt(x2 + ux * r, y2 + uy * r)} "
        f"C {_pt(x2 + ux * r - nx * k, y2 + uy * r - ny * k)} {_pt(b2[0] + ux * k, b2[1] + uy * k)} {_pt(*b2)} "
        f"L {_pt(*b1)} "
        f"C {_pt(b1[0] - ux * k, b1[1] - uy * k)} {_pt(x1 - ux * r - nx * k, y1 - uy * r - ny * k)} {_pt(x1 - ux * r, y1 - uy * r)} "
        f"C {_pt(x1 - ux * r + nx * k, y1 - uy * r + ny * k)} {_pt(a1[0] - ux * k, a1[1] - uy * k)} {_pt(*a1)} Z"
    )


def _eval_cubic(
    p0: tuple[float, float],
    p1: tuple[float, float],
    p2: tuple[float, float],
    p3: tuple[float, float],
    t: float,
) -> tuple[float, float]:
    u = 1.0 - t
    return (
        u**3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t**3 * p3[0],
        u**3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t**3 * p3[1],
    )


def _eval_cubic_tangent(
    p0: tuple[float, float],
    p1: tuple[float, float],
    p2: tuple[float, float],
    p3: tuple[float, float],
    t: float,
) -> tuple[float, float]:
    u = 1.0 - t
    tx = 3 * u * u * (p1[0] - p0[0]) + 6 * u * t * (p2[0] - p1[0]) + 3 * t * t * (p3[0] - p2[0])
    ty = 3 * u * u * (p1[1] - p0[1]) + 6 * u * t * (p2[1] - p1[1]) + 3 * t * t * (p3[1] - p2[1])
    length = math.hypot(tx, ty) or 1.0
    return tx / length, ty / length


def _thick_cubic_chain(
    segments: list[tuple[tuple[float, float], tuple[float, float], tuple[float, float], tuple[float, float]]],
    widths: Callable[[float], float],
    samples_per_seg: int = 18,
    ccw: bool = False,
) -> str:
    """Render a chain of cubic Beziers as a single smooth variable-width outline."""
    spine: list[tuple[float, float]] = []
    tangents: list[tuple[float, float]] = []
    for si, (p0, p1, p2, p3) in enumerate(segments):
        start_i = 0 if si == 0 else 1
        for i in range(start_i, samples_per_seg + 1):
            t = i / samples_per_seg
            spine.append(_eval_cubic(p0, p1, p2, p3, t))
            tangents.append(_eval_cubic_tangent(p0, p1, p2, p3, t))

    m = len(spine)
    left: list[tuple[float, float]] = []
    right: list[tuple[float, float]] = []
    for idx, ((x, y), (tx, ty)) in enumerate(zip(spine, tangents)):
        u = idx / max(1, m - 1)
        r = widths(u)
        nx, ny = -ty, tx
        left.append((x + nx * r, y + ny * r))
        right.append((x - nx * r, y - ny * r))

    ex, ey = spine[-1]
    etx, ety = tangents[-1]
    er = widths(1.0)
    end_cap = [(ex + etx * er * 0.9, ey + ety * er * 0.9)]

    sx, sy = spine[0]
    stx, sty = tangents[0]
    sr = widths(0.0)
    start_cap = [(sx - stx * sr * 0.9, sy - sty * sr * 0.9)]

    outline = left + end_cap + list(reversed(right)) + start_cap
    return _smooth_closed(outline, ccw=ccw)


def _mirror_x_pt(pt: tuple[float, float]) -> tuple[float, float]:
    return (2 * CENTER - pt[0], pt[1])


def _mirror_x_seg(
    seg: tuple[tuple[float, float], tuple[float, float], tuple[float, float], tuple[float, float]]
) -> tuple[tuple[float, float], tuple[float, float], tuple[float, float], tuple[float, float]]:
    return tuple(_mirror_x_pt(p) for p in seg)  # type: ignore[return-value]


# ─── Preset 1: caduceus (Hermes Caduceus) ────────────────────────────────────

def _build_caduceus() -> str:
    cx = CENTER
    paths: list[str] = []

    # Central finial orb & tapered staff (bold proportions for 32x32 clarity)
    paths.append(_circle(cx, 960.0, 255.0))
    paths.append(
        _polygon([
            (cx - 102.0, 1230.0),
            (cx + 102.0, 1230.0),
            (cx + 72.0, 4560.0),
            (cx, 4790.0),
            (cx - 72.0, 4560.0),
        ])
    )
    # Collar below finial
    paths.append(_rounded_rect(cx - 215.0, 1320.0, 430.0, 125.0, 62.0))

    # Symmetrical heraldic wings (3 distinct feathers each side with ~85u gaps)
    right_feathers = [
        # Top soaring pinion
        [(cx + 250.0, 1460.0), (cx + 820.0, 1180.0), (cx + 1680.0, 1020.0), (cx + 2010.0, 1100.0),
         (cx + 1830.0, 1380.0), (cx + 1180.0, 1550.0), (cx + 285.0, 1615.0)],
        # Middle feather (~85u below top feather)
        [(cx + 280.0, 1730.0), (cx + 1010.0, 1650.0), (cx + 1620.0, 1560.0), (cx + 1480.0, 1810.0),
         (cx + 960.0, 1915.0), (cx + 270.0, 1890.0)],
        # Lower pinion (~85u below middle feather)
        [(cx + 260.0, 2005.0), (cx + 820.0, 1995.0), (cx + 1230.0, 1980.0), (cx + 1090.0, 2195.0),
         (cx + 670.0, 2235.0), (cx + 240.0, 2165.0)],
    ]
    for feather in right_feathers:
        paths.append(_smooth_closed(feather))
        paths.append(_smooth_closed([_mirror_x_pt(p) for p in feather]))

    # Twin intertwining serpents shifted cleanly below the wings (y=2320..4480)
    s_segs = [
        ((cx - 330.0, 2360.0), (cx - 40.0, 2220.0), (cx + 820.0, 2500.0), (cx + 710.0, 2900.0)),
        ((cx + 710.0, 2900.0), (cx + 600.0, 3260.0), (cx - 700.0, 3260.0), (cx - 600.0, 3690.0)),
        ((cx - 600.0, 3690.0), (cx - 500.0, 4080.0), (cx + 450.0, 4150.0), (cx + 160.0, 4520.0)),
    ]

    def width_fn(u: float) -> float:
        if u < 0.08:
            return 110.0
        return 102.0 * (1.0 - 0.55 * max(0.0, (u - 0.5) / 0.5))

    paths.append(_thick_cubic_chain(s_segs, width_fn, samples_per_seg=20))
    paths.append(_thick_cubic_chain([_mirror_x_seg(s) for s in s_segs], width_fn, samples_per_seg=20))

    # Stylized serpent heads facing inward with clean gap below lower wing feathers
    head_r = [
        (cx - 250.0, 2265.0),
        (cx - 485.0, 2335.0),
        (cx - 500.0, 2485.0),
        (cx - 260.0, 2475.0),
    ]
    paths.append(_smooth_closed(head_r))
    paths.append(_smooth_closed([_mirror_x_pt(p) for p in head_r]))

    return " ".join(paths)


# ─── Preset 2: winged-helmet (Hermes Petasos) ────────────────────────────────

def _build_winged_helmet() -> str:
    cx = CENTER
    paths: list[str] = []

    # Classic rounded traveler's helmet dome
    dome = [
        (cx, 1360.0),
        (cx + 610.0, 1400.0),
        (cx + 960.0, 1880.0),
        (cx + 1040.0, 2920.0),
        (cx - 1040.0, 2920.0),
        (cx - 960.0, 1880.0),
        (cx - 610.0, 1400.0),
    ]
    paths.append(_smooth_closed(dome))

    # Wide curved Petasos brim
    brim = [
        (cx, 2860.0),
        (cx + 1260.0, 2880.0),
        (cx + 2180.0, 2780.0),
        (cx + 2260.0, 3080.0),
        (cx + 1480.0, 3560.0),
        (cx, 3680.0),
        (cx - 1480.0, 3560.0),
        (cx - 2260.0, 3080.0),
        (cx - 2180.0, 2780.0),
        (cx - 1260.0, 2880.0),
    ]
    paths.append(_smooth_closed(brim))

    # Crisp arched hatband groove separating dome crown from brim (ccw=True cutout)
    band_segs = [
        ((cx - 980.0, 2760.0), (cx - 400.0, 2600.0), (cx + 400.0, 2600.0), (cx + 980.0, 2760.0)),
    ]
    paths.append(_thick_cubic_chain(band_segs, lambda _u: 88.0, samples_per_seg=22, ccw=True))

    # 3 distinct swept feathers on each side with ~85u gaps between feathers & from dome
    right_wings = [
        [(cx + 1140.0, 1920.0), (cx + 1680.0, 1400.0), (cx + 2240.0, 1080.0), (cx + 2310.0, 1340.0),
         (cx + 1860.0, 1780.0), (cx + 1200.0, 2120.0)],
        [(cx + 1180.0, 2240.0), (cx + 1780.0, 1910.0), (cx + 2270.0, 1800.0), (cx + 2110.0, 2110.0),
         (cx + 1620.0, 2330.0), (cx + 1200.0, 2410.0)],
        [(cx + 1200.0, 2525.0), (cx + 1660.0, 2360.0), (cx + 1990.0, 2350.0), (cx + 1810.0, 2620.0),
         (cx + 1410.0, 2720.0), (cx + 1180.0, 2690.0)],
    ]
    for w in right_wings:
        paths.append(_smooth_closed(w))
        paths.append(_smooth_closed([_mirror_x_pt(p) for p in w]))

    # Top helmet crest knob
    paths.append(_circle(cx, 1270.0, 155.0))

    return " ".join(paths)


# ─── Preset 3: winged-sandal (Talaria Winged Sandal) ──────────────────────────

def _build_winged_sandal() -> str:
    paths: list[str] = []

    # 1. Sleek curved sandal sole with upturned toe
    sole_segs = [
        ((1060.0, 3840.0), (1950.0, 4140.0), (3250.0, 4180.0), (4340.0, 3680.0)),
    ]
    paths.append(
        _thick_cubic_chain(
            sole_segs,
            lambda u: 165.0 if u < 0.8 else 165.0 * (1.0 - 0.35 * (u - 0.8) / 0.2),
            samples_per_seg=26,
        )
    )

    # 2. Heel cup & ankle cuff
    heel = [
        (1120.0, 3840.0),
        (1120.0, 2960.0),
        (1640.0, 2780.0),
        (2020.0, 3040.0),
        (2140.0, 3680.0),
        (1780.0, 3900.0),
    ]
    paths.append(_smooth_closed(heel))

    # 3. Instep foot strap & toe strap arching down to the sole
    paths.append(_capsule(1920.0, 3160.0, 3040.0, 3880.0, 125.0))
    paths.append(_capsule(2920.0, 3400.0, 3780.0, 3840.0, 110.0))

    # Negative-space sandal ankle cutout
    paths.append(_circle(1610.0, 3380.0, 165.0, ccw=True))

    # 4. 3 clearly separated heraldic wing pinions rising above the ankle (~80u gaps)
    wing_feathers = [
        # Long soaring top pinion
        [(1640.0, 2660.0), (2220.0, 1780.0), (3180.0, 1120.0), (4220.0, 960.0),
         (3920.0, 1460.0), (3040.0, 2040.0), (1860.0, 2760.0)],
        # Middle wing pinion (~85u gap)
        [(1940.0, 2860.0), (2680.0, 2220.0), (3760.0, 1820.0), (3500.0, 2240.0),
         (2740.0, 2620.0), (2060.0, 2960.0)],
        # Lower pinion (~85u gap above straps)
        [(2150.0, 3070.0), (2800.0, 2720.0), (3440.0, 2560.0), (3190.0, 2900.0),
         (2610.0, 3090.0), (2180.0, 3180.0)],
    ]
    for f in wing_feathers:
        paths.append(_smooth_closed(f))

    return " ".join(paths)


# ─── Preset 4: monogram-h (Geometric H Monogram) ─────────────────────────────

def _build_monogram_h() -> str:
    cx, cy = CENTER, CENTER
    paths: list[str] = []

    def octagon(r: float) -> list[tuple[float, float]]:
        pts = []
        for i in range(8):
            ang = math.radians(22.5 + i * 45.0)
            pts.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
        return pts

    # Outer octagonal bezel (CW solid + CCW inner cutout)
    paths.append(_polygon(octagon(2140.0), ccw=False))
    paths.append(_polygon(octagon(1720.0), ccw=True))

    # Architectural H (pillars + crossbar union cleanly via nonzero winding)
    pillar_w = 400.0
    gap_half = 460.0
    h_top = cy - 990.0
    h_bot = cy + 990.0

    paths.append(_rounded_rect(cx - gap_half - pillar_w, h_top, pillar_w, h_bot - h_top, 95.0))
    paths.append(_rounded_rect(cx + gap_half, h_top, pillar_w, h_bot - h_top, 95.0))

    bar_h = 340.0
    paths.append(
        _polygon(
            [
                (cx - gap_half - 100.0, cy - bar_h / 2),
                (cx + gap_half + 100.0, cy - bar_h / 2),
                (cx + gap_half + 100.0, cy + bar_h / 2),
                (cx - gap_half - 100.0, cy + bar_h / 2),
            ],
            ccw=False,
        )
    )

    # Center diamond aperture cutout (CCW)
    paths.append(
        _polygon(
            [
                (cx, cy - 105.0),
                (cx + 145.0, cy),
                (cx, cy + 105.0),
                (cx - 145.0, cy),
            ],
            ccw=True,
        )
    )

    return " ".join(paths)


# ─── Preset 5: neural-core (Orbital Constellation / Node) ─────────────────────

def _build_neural_core() -> str:
    cx, cy = CENTER, CENTER
    paths: list[str] = []

    orbit_r = 1660.0
    node_r = 350.0
    core_r = 710.0

    # 1. All CW solid shapes first: spokes, hexagonal struts, outer nodes, central core
    for i in range(6):
        ang = math.radians(-90.0 + i * 60.0)
        nx = cx + orbit_r * math.cos(ang)
        ny = cy + orbit_r * math.sin(ang)
        # Spoke ends well clear of inner core spark (r=410) and outer node holes (r=145)
        sx = cx + (core_r - 70.0) * math.cos(ang)
        sy = cy + (core_r - 70.0) * math.sin(ang)
        ex = cx + (orbit_r - node_r + 70.0) * math.cos(ang)
        ey = cy + (orbit_r - node_r + 70.0) * math.sin(ang)
        paths.append(_capsule(sx, sy, ex, ey, 95.0))
        paths.append(_circle(nx, ny, node_r, ccw=False))

    for i in range(6):
        a1 = math.radians(-90.0 + i * 60.0)
        a2 = math.radians(-90.0 + ((i + 1) % 6) * 60.0)
        x1, y1 = cx + orbit_r * math.cos(a1), cy + orbit_r * math.sin(a1)
        x2, y2 = cx + orbit_r * math.cos(a2), cy + orbit_r * math.sin(a2)
        dx, dy = x2 - x1, y2 - y1
        dist = math.hypot(dx, dy)
        ux, uy = dx / dist, dy / dist
        pad = node_r - 40.0
        paths.append(_capsule(x1 + ux * pad, y1 + uy * pad, x2 - ux * pad, y2 - uy * pad, 68.0))

    paths.append(_circle(cx, cy, core_r, ccw=False))

    # 2. CCW cutouts: 6 orbital node holes + central 4-point star spark
    for i in range(6):
        ang = math.radians(-90.0 + i * 60.0)
        nx = cx + orbit_r * math.cos(ang)
        ny = cy + orbit_r * math.sin(ang)
        paths.append(_circle(nx, ny, 145.0, ccw=True))

    s_outer = 410.0
    s_inner = 125.0
    paths.append(
        _polygon(
            [
                (cx, cy - s_outer),
                (cx + s_inner, cy - s_inner),
                (cx + s_outer, cy),
                (cx + s_inner, cy + s_inner),
                (cx, cy + s_outer),
                (cx - s_inner, cy + s_inner),
                (cx - s_outer, cy),
                (cx - s_inner, cy - s_inner),
            ],
            ccw=True,
        )
    )

    return " ".join(paths)


# ─── Preset 6: compass (Wayfinder Compass) ────────────────────────────────────

def _build_compass() -> str:
    cx, cy = CENTER, CENTER
    paths: list[str] = []

    # Outer bezel ring (CW outer + CCW inner)
    paths.append(_circle(cx, cy, 2100.0, ccw=False))
    paths.append(_circle(cx, cy, 1740.0, ccw=True))

    # Single non-overlapping 16-vertex 8-point compass rose (CW, winding = +1 everywhere)
    star_pts: list[tuple[float, float]] = []
    for i in range(8):
        ang = math.radians(-90.0 + i * 45.0)
        valley_ang = math.radians(-90.0 + i * 45.0 + 22.5)
        tip_r = 1700.0 if (i % 2 == 0) else 1180.0
        star_pts.append((cx + tip_r * math.cos(ang), cy + tip_r * math.sin(ang)))
        star_pts.append((cx + 420.0 * math.cos(valley_ang), cy + 420.0 * math.sin(valley_ang)))
    paths.append(_polygon(star_pts, ccw=False))

    # Perfect circular center hole (CCW)
    paths.append(_circle(cx, cy, 200.0, ccw=True))

    return " ".join(paths)


# ─── Preset 7: terminal (Developer Terminal) ─────────────────────────────────

def _build_terminal() -> str:
    cx, cy = CENTER, CENTER
    paths: list[str] = []

    w, h = 4040.0, 3500.0
    x0, y0 = cx - w / 2, cy - h / 2
    border = 265.0
    titlebar_h = 820.0

    # 1. Outer rounded frame (CW)
    paths.append(_rounded_rect(x0, y0, w, h, 520.0, ccw=False))

    # 2. 3 window control dots punched out of solid titlebar (CCW)
    for i in range(3):
        paths.append(_circle(x0 + 580.0 + i * 330.0, y0 + 440.0, 115.0, ccw=True))

    # 3. Lower terminal screen pane cutout (CCW)
    paths.append(
        _rounded_rect(
            x0 + border,
            y0 + titlebar_h,
            w - 2 * border,
            h - titlebar_h - border,
            240.0,
            ccw=True,
        )
    )

    # 4. Bold ">_" prompt inside the screen pane (CW; two overlapping capsules of '>' union cleanly)
    pane_cy = y0 + titlebar_h + (h - titlebar_h - border) / 2.0
    chev_x0 = cx - 960.0
    chev_x1 = cx - 200.0
    chev_h = 540.0
    paths.append(_capsule(chev_x0, pane_cy - chev_h, chev_x1, pane_cy, 150.0, ccw=False))
    paths.append(_capsule(chev_x1, pane_cy, chev_x0, pane_cy + chev_h, 150.0, ccw=False))
    paths.append(_capsule(cx + 140.0, pane_cy + chev_h, cx + 1000.0, pane_cy + chev_h, 150.0, ccw=False))

    return " ".join(paths)


# ─── Preset 8: shield (Aegis Crest) ───────────────────────────────────────────

def _build_shield() -> str:
    cx = CENTER
    paths: list[str] = []

    # 1. Outer shield (CW)
    outer_pts = [
        (cx, 760.0),
        (cx + 1740.0, 1220.0),
        (cx + 1680.0, 2660.0),
        (cx + 1140.0, 3860.0),
        (cx, 4720.0),
        (cx - 1140.0, 3860.0),
        (cx - 1680.0, 2660.0),
        (cx - 1740.0, 1220.0),
    ]
    paths.append(_smooth_closed(outer_pts, ccw=False))

    # 2. Inner shield rim cutout (CCW)
    inner_pts = [
        (cx, 1120.0),
        (cx + 1380.0, 1480.0),
        (cx + 1320.0, 2620.0),
        (cx + 880.0, 3600.0),
        (cx, 4300.0),
        (cx - 880.0, 3600.0),
        (cx - 1320.0, 2620.0),
        (cx - 1380.0, 1480.0),
    ]
    paths.append(_smooth_closed(inner_pts, ccw=True))

    # 3. Inner core shield (CW)
    core_pts = [
        (cx, 1460.0),
        (cx + 1020.0, 1740.0),
        (cx + 960.0, 2560.0),
        (cx + 620.0, 3300.0),
        (cx, 3840.0),
        (cx - 620.0, 3300.0),
        (cx - 960.0, 2560.0),
        (cx - 1020.0, 1740.0),
    ]
    paths.append(_smooth_closed(core_pts, ccw=False))

    # 4. Crisp upward chevron + diamond cutouts (CCW)
    paths.append(
        _polygon(
            [
                (cx, 2040.0),
                (cx + 620.0, 2660.0),
                (cx + 420.0, 2880.0),
                (cx, 2460.0),
                (cx - 420.0, 2880.0),
                (cx - 620.0, 2660.0),
            ],
            ccw=True,
        )
    )
    paths.append(
        _polygon(
            [
                (cx, 2720.0),
                (cx + 360.0, 3080.0),
                (cx, 3440.0),
                (cx - 360.0, 3080.0),
            ],
            ccw=True,
        )
    )

    return " ".join(paths)


PRESETS: dict[str, Preset] = {
    "caduceus": Preset(
        id="caduceus",
        name="Hermes Caduceus",
        tagline="Classic winged staff with twin serpents",
        description="Traditional symbol of Hermes matching the Hermes TUI glyph.",
        build_path=_build_caduceus,
    ),
    "winged-helmet": Preset(
        id="winged-helmet",
        name="Hermes Petasos",
        tagline="Sleek geometric winged traveller's helm",
        description="Winged Petasos traveler's helmet with arched brim and swept wings.",
        build_path=_build_winged_helmet,
    ),
    "winged-sandal": Preset(
        id="winged-sandal",
        name="Talaria Wing",
        tagline="Classic winged sandal emblem",
        description="Iconic Talaria winged Greek sandal with sweeping heraldic feathers.",
        build_path=_build_winged_sandal,
    ),
    "monogram-h": Preset(
        id="monogram-h",
        name="Geometric H Monogram",
        tagline="Architectural 'H' in octagonal frame",
        description="Bold geometric H monogram framed by a chamfered octagon.",
        build_path=_build_monogram_h,
    ),
    "neural-core": Preset(
        id="neural-core",
        name="Orbital Constellation",
        tagline="Central hub & hexagonal orbital lattice",
        description="Hexagonal lattice surrounding a 4-point star core.",
        build_path=_build_neural_core,
    ),
    "compass": Preset(
        id="compass",
        name="Wayfinder Compass",
        tagline="Precision 8-point navigational compass",
        description="Crisp 8-point compass rose inside a precision circular bezel.",
        build_path=_build_compass,
    ),
    "terminal": Preset(
        id="terminal",
        name="Developer Terminal",
        tagline="Command prompt glyph in technical frame",
        description="Minimalist rounded terminal window with a bold >_ prompt.",
        build_path=_build_terminal,
    ),
    "shield": Preset(
        id="shield",
        name="Aegis Crest",
        tagline="Minimalist enterprise shield emblem",
        description="Layered shield crest with centered wing-chevron insignia.",
        build_path=_build_shield,
    ),
}

PRESET_ORDER = [
    "caduceus",
    "winged-helmet",
    "winged-sandal",
    "monogram-h",
    "neural-core",
    "compass",
    "terminal",
    "shield",
]


def build_preset_svg(preset_id: str, fill: str = "#000000") -> str:
    if preset_id not in PRESETS:
        raise ValueError(f"Unknown preset: {preset_id!r}")
    d = PRESETS[preset_id].build_path()
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {VIEWBOX} {VIEWBOX}" width="{VIEWBOX}" height="{VIEWBOX}">\n'
        f'  <path d="{d}" fill="{fill}"/>\n'
        f"</svg>\n"
    )
