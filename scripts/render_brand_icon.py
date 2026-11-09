#!/usr/bin/env python3
"""Render brand/icon.svg to the PNG sizes the Home Assistant brands repo wants.

No SVG rasteriser is assumed to be installed, so this walks the icon's own XML
and redraws it with Pillow at 8x, then downsamples. It understands exactly the
subset of SVG that brand/icon.svg uses - a vertical linear gradient, rounded
rects (filled or stroked, optionally masked) and one triangular path. Edit the
SVG, re-run this, and the PNGs follow.

    python3 scripts/render_brand_icon.py
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image, ImageDraw

SVG_NS = "{http://www.w3.org/2000/svg}"
SUPERSAMPLE = 8
SIZES = {"icon.png": 256, "icon@2x.png": 512}

BRAND_DIR = Path(__file__).resolve().parent.parent / "brand"


def _f(el: ET.Element, name: str, default: float = 0.0) -> float:
    value = el.get(name)
    return default if value is None else float(value)


def _rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    if len(value) == 3:
        value = "".join(c * 2 for c in value)
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))


def _gradient(stops: list[tuple[int, int, int]], n: int) -> Image.Image:
    top, bottom = stops[0], stops[-1]
    column = Image.new("RGB", (1, n))
    draw = ImageDraw.Draw(column)
    for y in range(n):
        t = y / (n - 1)
        draw.point(
            (0, y),
            tuple(round(top[i] + (bottom[i] - top[i]) * t) for i in range(3)),
        )
    return column.resize((n, n))


def _triangle(d: str, k) -> list[tuple[float, float]]:
    """Parse the icon's single path, of the form 'M x y h run L x y Z'."""
    start, rest = d.replace("Z", "").strip().removeprefix("M").split("h")
    mx, my = (float(v) for v in start.split())
    run, apex = rest.split("L")
    ax, ay = (float(v) for v in apex.split())
    return [(k(mx), k(my)), (k(mx + float(run)), k(my)), (k(ax), k(ay))]


def _rounded(draw: ImageDraw.ImageDraw, el: ET.Element, k, **kwargs) -> None:
    """Draw an SVG rect. SVG centres a stroke on the path, Pillow insets it."""
    x, y = _f(el, "x"), _f(el, "y")
    w, h = _f(el, "width"), _f(el, "height")
    r = _f(el, "rx")
    inset = kwargs.pop("stroke_width", 0) / 2
    draw.rounded_rectangle(
        (k(x - inset), k(y - inset), k(x + w + inset), k(y + h + inset)),
        radius=k(r + inset),
        **kwargs,
    )


def render(svg_path: Path, px: int) -> Image.Image:
    """Rasterise the icon to a square px-by-px RGBA image."""
    root = ET.parse(svg_path).getroot()
    _, _, vw, _vh = (float(v) for v in root.get("viewBox").split())
    n = px * SUPERSAMPLE

    def k(v: float) -> float:
        return v * n / vw

    gradients: dict[str, list[tuple[int, int, int]]] = {}
    masks: dict[str, ET.Element] = {}
    for defs in root.findall(f"{SVG_NS}defs"):
        for grad in defs.findall(f"{SVG_NS}linearGradient"):
            gradients[grad.get("id")] = [
                _rgb(s.get("stop-color")) for s in grad.findall(f"{SVG_NS}stop")
            ]
        for mask in defs.findall(f"{SVG_NS}mask"):
            masks[mask.get("id")] = mask

    canvas = Image.new("RGBA", (n, n), (0, 0, 0, 0))

    def mask_image(ref: str | None) -> Image.Image | None:
        if not ref:
            return None
        mask = masks[ref.removeprefix("url(#").rstrip(")")]
        img = Image.new("L", (n, n), 0)
        md = ImageDraw.Draw(img)
        for child in mask:
            _rounded(md, child, k, fill=255 if _rgb(child.get("fill"))[0] else 0)
        return img

    def paint(el: ET.Element, inherited: dict[str, str]) -> None:
        attrs = {**inherited, **el.attrib}
        tag = el.tag.removeprefix(SVG_NS)

        if tag == "g":
            for child in el:
                paint(child, attrs)
            return

        stroke = attrs.get("stroke", "none")
        fill = attrs.get("fill", "#000000")
        layer = Image.new("RGBA", (n, n), (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)

        if stroke != "none":
            alpha = round(255 * float(attrs.get("stroke-opacity", 1)))
            width = float(attrs.get("stroke-width", 1))
            _rounded(
                draw,
                el,
                k,
                outline=(*_rgb(stroke), alpha),
                width=round(k(width)),
                stroke_width=width,
            )
        elif fill.startswith("url(#"):
            gradient = _gradient(gradients[fill.removeprefix("url(#").rstrip(")")], n)
            shape = Image.new("L", (n, n), 0)
            _rounded(ImageDraw.Draw(shape), el, k, fill=255)
            layer.paste(gradient, (0, 0), shape)
        elif tag == "rect":
            _rounded(draw, el, k, fill=_rgb(fill))
        elif tag == "path":
            draw.polygon(_triangle(el.get("d"), k), fill=_rgb(fill))

        canvas.alpha_composite(
            Image.composite(layer, Image.new("RGBA", (n, n)), m)
            if (m := mask_image(attrs.get("mask")))
            else layer
        )

    for el in root:
        if el.tag != f"{SVG_NS}defs":
            paint(el, {})

    return canvas.resize((px, px), Image.LANCZOS)


def main() -> None:
    """Write every PNG size next to the SVG."""
    svg = BRAND_DIR / "icon.svg"
    for name, px in SIZES.items():
        out = BRAND_DIR / name
        render(svg, px).save(out, optimize=True)
        print(f"{out.relative_to(BRAND_DIR.parent)}  {px}x{px}")


if __name__ == "__main__":
    main()
