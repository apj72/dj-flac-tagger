#!/usr/bin/env python3
"""Remove the flat light 'plate' behind tab icons so mask-image + currentColor works."""
from __future__ import annotations

import argparse
import math
from pathlib import Path

from PIL import Image


def avg_corner_rgb(im: Image.Image) -> tuple[float, float, float]:
    w, h = im.size
    corners = [
        im.getpixel((0, 0))[:3],
        im.getpixel((w - 1, 0))[:3],
        im.getpixel((0, h - 1))[:3],
        im.getpixel((w - 1, h - 1))[:3],
    ]
    return tuple(sum(c[i] for c in corners) / 4 for i in range(3))


def strip_plate(im: Image.Image, tol: float, feather: float) -> Image.Image:
    im = im.convert("RGBA")
    bg = avg_corner_rgb(im)
    w, h = im.size
    out = Image.new("RGBA", (w, h))
    op = out.load()
    ip = im.load()
    for y in range(h):
        for x in range(w):
            r, g, b, a = ip[x, y]
            if a == 0:
                op[x, y] = (0, 0, 0, 0)
                continue
            dist = math.sqrt((r - bg[0]) ** 2 + (g - bg[1]) ** 2 + (b - bg[2]) ** 2)
            if dist <= tol:
                na = 0
            elif dist >= tol + feather:
                na = a
            else:
                na = int(round(a * (dist - tol) / feather))
            op[x, y] = (r, g, b, na)
    return out


def drop_light_plate_residue(im: Image.Image, lum_cutoff: float, feather: float) -> Image.Image:
    """Remove baked checkerboard / light plate pixels (high luminance) after strip_plate.

    Exports sometimes leave ~RGB(200–220) pixels at varying alpha; those read as a
    checkerboard when used as a CSS mask. Dark line art stays below ~120.
    """
    im = im.convert("RGBA")
    w, h = im.size
    out = Image.new("RGBA", (w, h))
    op = out.load()
    ip = im.load()
    lo = lum_cutoff - feather
    for y in range(h):
        for x in range(w):
            r, g, b, a = ip[x, y]
            if a == 0:
                op[x, y] = (0, 0, 0, 0)
                continue
            lum = 0.299 * r + 0.587 * g + 0.114 * b
            if lum >= lum_cutoff:
                na = 0
            elif lum <= lo:
                na = a
            else:
                na = int(round(a * (lum_cutoff - lum) / max(feather, 1e-6)))
            op[x, y] = (r, g, b, na)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--dir",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "static" / "icons" / "tabs",
        help="Folder containing PNG tab icons",
    )
    ap.add_argument("--tol", type=float, default=42.0, help="RGB distance treated as plate")
    ap.add_argument("--feather", type=float, default=28.0, help="Anti-alias band width")
    ap.add_argument(
        "--lum-cutoff",
        type=float,
        default=193.0,
        help="Remove pixels with luminance >= this (plate / checkerboard residue)",
    )
    ap.add_argument(
        "--lum-feather",
        type=float,
        default=14.0,
        help="Feather band below lum-cutoff (smooth plate edge)",
    )
    args = ap.parse_args()
    for path in sorted(args.dir.glob("*.png")):
        img = strip_plate(Image.open(path), args.tol, args.feather)
        img = drop_light_plate_residue(img, args.lum_cutoff, args.lum_feather)
        img.save(path, optimize=True)
        print(path.name)


if __name__ == "__main__":
    main()
