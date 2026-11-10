"""The brand icon ships in three places; these keep them from drifting apart."""

from __future__ import annotations

import base64
import struct
import xml.etree.ElementTree as ET
from pathlib import Path

from custom_components.companion_apk.http_views import ICON_DATA_URI, ICON_SVG

SVG_NS = "{http://www.w3.org/2000/svg}"
REPO_DIR = Path(__file__).resolve().parents[1]
SVG_PATH = REPO_DIR / "brand" / "icon.svg"

# Home Assistant 2026.3+ only picks the icon up from this exact path.
PNG_DIR = REPO_DIR / "custom_components" / "companion_apk" / "brand"


def _shapes(svg: str) -> list[tuple[str, dict[str, str]]]:
    """Flatten an SVG into its drawable elements, ignoring document chrome."""
    root = ET.fromstring(svg)
    return [
        (el.tag.removeprefix(SVG_NS), dict(el.attrib))
        for el in root.iter()
        if el is not root and el.tag != f"{SVG_NS}defs"
    ]


def _png_size(path: Path) -> tuple[int, int]:
    """Read width and height out of a PNG's IHDR chunk."""
    header = path.read_bytes()[:24]
    assert header[:8] == b"\x89PNG\r\n\x1a\n", f"{path.name} is not a PNG"
    return struct.unpack(">II", header[16:24])


def test_inline_icon_matches_brand_source():
    source = SVG_PATH.read_text(encoding="utf-8")
    assert _shapes(ICON_SVG) == _shapes(source)
    assert ET.fromstring(ICON_SVG).get("viewBox") == ET.fromstring(source).get(
        "viewBox"
    )


def test_icon_data_uri_is_decodable_svg():
    prefix = "data:image/svg+xml;base64,"
    assert ICON_DATA_URI.startswith(prefix)
    decoded = base64.b64decode(ICON_DATA_URI.removeprefix(prefix)).decode("utf-8")
    assert decoded == ICON_SVG


def test_brand_pngs_are_where_home_assistant_looks_for_them():
    """The icon only reaches the UI from custom_components/<domain>/brand/."""
    assert _png_size(PNG_DIR / "icon.png") == (256, 256)
    assert _png_size(PNG_DIR / "icon@2x.png") == (512, 512)
