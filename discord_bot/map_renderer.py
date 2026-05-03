from __future__ import annotations

import os
import re
import sqlite3
import subprocess
import tempfile

from lxml import etree

from discord_bot.ww1_data import DB_PATH, SERVER_ID, SCENARIO_ID

SVG_PATH = "All Complete.svg"

# Full viewBox covering all province content (mm units)
# Discovered by sampling first-coord of every province path after scale(0.26458333)
# X: 75–465, Y: 1–225  → add small padding
MAP_VIEWBOX = "65 -5 415 240"

RSVG_CONVERT = "/nix/store/9gwwn0yb3zj0vr1rn6ix2bia57ahksry-librsvg-2.60.0/bin/rsvg-convert"

COUNTRY_COLORS: dict[str, str] = {
    "germany":         "#4A90E2",
    "united_kingdom":  "#D0021B",
    "france":          "#50E3C2",
    "russian_empire":  "#9013FE",
    "austrian_empire": "#F5A623",
    "ottoman":         "#8B572A",
    "italy":           "#7ED321",
    "spain":           "#BD10E0",
    "netherlands":     "#417505",
    "belgium":         "#F8E71C",
    "sweden":          "#4A4A4A",
    "denmark":         "#B8E986",
    "norway":          "#2C3E50",
    "portugal":        "#E67E22",
    "switzerland":     "#E74C3C",
    "greece":          "#3498DB",
    "serbia":          "#34495E",
    "bulgaria":        "#27AE60",
    "romania":         "#F39C12",
    "albania":         "#C0392B",
}

DEFAULT_COLOR  = "#CCCCCC"
INKSCAPE_NS    = "http://www.inkscape.org/namespaces/inkscape"
LABEL_ATTR     = f"{{{INKSCAPE_NS}}}label"
_FILL_RE       = re.compile(r"(?<![a-zA-Z-])fill\s*:[^;]+")
_OPACITY_RE    = re.compile(r"fill-opacity\s*:[^;]+")


def _normalize(s: str) -> str:
    return s.strip().lower().replace(" ", "")


def _get_owner_map() -> dict[str, str]:
    """Return {normalized_province_name: country_id} for every province."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT province_name, owner_country FROM provinces "
        "WHERE server_id=? AND scenario_id=?",
        (SERVER_ID, SCENARIO_ID),
    ).fetchall()
    conn.close()
    return {_normalize(r["province_name"]): r["owner_country"] for r in rows}


def _apply_fill(style: str, color: str) -> str:
    """Replace fill color and ensure full opacity in a CSS style string."""
    clean = style.replace(" ", "")
    if "display:none" in clean or "fill:none" in clean:
        return style

    if "fill:" in style:
        style = _FILL_RE.sub(f"fill:{color}", style)
    else:
        style = f"fill:{color};" + style

    if "fill-opacity:" in style:
        style = _OPACITY_RE.sub("fill-opacity:1", style)
    else:
        style += ";fill-opacity:1"

    return style


def render_map_png(output_width: int = 1400) -> bytes:
    """Color every province by its current owner and return PNG bytes."""
    owner_map = _get_owner_map()

    parser = etree.XMLParser(remove_blank_text=False, recover=True)
    tree   = etree.parse(SVG_PATH, parser)
    root   = tree.getroot()

    # Remove sodipodi:namedview (contains Inkscape page-color metadata that
    # rsvg-convert may interpret as a white background rect)
    for el in list(root):
        if "namedview" in el.tag:
            root.remove(el)

    # Remove unlabeled paths — these are 1500+ text-label halo/glyph paths
    # rendered as white near-opaque fills that sit on top of province fills
    # and make all provinces appear white.
    for el in list(root.iter()):
        if el.tag.split("}")[-1] != "path":
            continue
        if not (el.get(LABEL_ATTR) or "").strip():
            parent = el.getparent()
            if parent is not None:
                parent.remove(el)

    # Fix the viewBox so rsvg-convert renders the actual map area
    root.set("viewBox", MAP_VIEWBOX)
    root.set("width",  "415mm")
    root.set("height", "240mm")

    colored = 0
    for elem in root.iter():
        label = (elem.get(LABEL_ATTR) or "").strip()
        if not label or label == "Layer 1":
            continue

        country_id = owner_map.get(_normalize(label))
        if country_id is None:
            color = DEFAULT_COLOR
        else:
            color = COUNTRY_COLORS.get(country_id, DEFAULT_COLOR)

        style = elem.get("style", "")
        new_style = _apply_fill(style, color)
        if new_style != style:
            elem.set("style", new_style)
        elif elem.get("fill") is not None:
            elem.set("fill", color)

        colored += 1

    svg_bytes = etree.tostring(root, xml_declaration=True, encoding="UTF-8")

    # Write to temp file and convert with rsvg-convert (handles Inkscape SVGs)
    with tempfile.NamedTemporaryFile(suffix=".svg", delete=False) as svg_tmp:
        svg_tmp.write(svg_bytes)
        svg_path = svg_tmp.name

    png_path = svg_path.replace(".svg", ".png")
    try:
        subprocess.run(
            [RSVG_CONVERT, "-w", str(output_width), svg_path, "-o", png_path],
            check=True,
            timeout=60,
            capture_output=True,
        )
        with open(png_path, "rb") as f:
            return f.read()
    finally:
        for p in (svg_path, png_path):
            try:
                os.unlink(p)
            except FileNotFoundError:
                pass
