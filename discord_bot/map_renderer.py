from __future__ import annotations

import logging
import os
import re
import sqlite3
import subprocess
import tempfile

from lxml import etree

from discord_bot.ww1_data import DB_PATH, SCENARIO_ID

log = logging.getLogger(__name__)

SVG_PATH = "All Complete.svg"

# Full viewBox covering all province content (mm units, after scale(0.26458333))
MAP_VIEWBOX = "65 -5 415 240"

RSVG_CONVERT = "/nix/store/9gwwn0yb3zj0vr1rn6ix2bia57ahksry-librsvg-2.60.0/bin/rsvg-convert"

# country_id → hex fill color  (SVG rendering ONLY — never use color names here)
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

# country_id → human-readable display name  (Discord embed / legend ONLY)
COUNTRY_DISPLAY_NAMES: dict[str, str] = {
    "germany":         "German Empire",
    "united_kingdom":  "United Kingdom",
    "france":          "France",
    "russian_empire":  "Russian Empire",
    "austrian_empire": "Austrian Empire",
    "ottoman":         "Ottoman Empire",
    "italy":           "Italy",
    "spain":           "Spain",
    "netherlands":     "Netherlands",
    "belgium":         "Belgium",
    "sweden":          "Sweden",
    "denmark":         "Denmark",
    "norway":          "Norway",
    "portugal":        "Portugal",
    "switzerland":     "Switzerland",
    "greece":          "Greece",
    "serbia":          "Serbia",
    "bulgaria":        "Bulgaria",
    "romania":         "Romania",
    "albania":         "Albania",
}

# country_id → plain English color name  (Discord embed / legend ONLY)
COUNTRY_COLOR_NAMES: dict[str, str] = {
    "germany":         "Blue",
    "united_kingdom":  "Red",
    "france":          "Teal",
    "russian_empire":  "Purple",
    "austrian_empire": "Orange",
    "ottoman":         "Brown",
    "italy":           "Green",
    "spain":           "Violet",
    "netherlands":     "Dark Green",
    "belgium":         "Yellow",
    "sweden":          "Dark Grey",
    "denmark":         "Light Green",
    "norway":          "Navy",
    "portugal":        "Amber",
    "switzerland":     "Crimson",
    "greece":          "Sky Blue",
    "serbia":          "Slate",
    "bulgaria":        "Emerald",
    "romania":         "Gold",
    "albania":         "Dark Red",
}

DEFAULT_COLOR  = "#CCCCCC"
INKSCAPE_NS    = "http://www.inkscape.org/namespaces/inkscape"
LABEL_ATTR     = f"{{{INKSCAPE_NS}}}label"
_FILL_RE       = re.compile(r"(?<![a-zA-Z-])fill\s*:[^;]+")
_OPACITY_RE    = re.compile(r"fill-opacity\s*:[^;]+")


def _normalize(s: str) -> str:
    return s.strip().lower().replace(" ", "")


def _get_owner_map(server_id: str) -> dict[str, str]:
    """
    Return {normalized_province_name: country_id} for every province in this server.
    Keys are lowercase, space-stripped province names (matching inkscape:label values).
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT province_name, owner_country FROM provinces "
        "WHERE server_id=? AND scenario_id=?",
        (server_id, SCENARIO_ID),
    ).fetchall()
    conn.close()

    result: dict[str, str] = {}
    for r in rows:
        owner = r["owner_country"]
        if owner is None:
            continue
        result[_normalize(r["province_name"])] = str(owner)
    return result


def _apply_fill(style: str, color: str) -> str:
    """
    Replace fill with a hex color and ensure full opacity in a CSS style string.
    The color argument must always be a hex value like '#4A90E2'.
    """
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


def render_map_png(output_width: int = 1400, server_id: str = "guild_demo") -> bytes:
    """
    Color every province path by its current owner and return PNG bytes.

    Rendering rules:
    - SVG fills are ALWAYS hex colors from COUNTRY_COLORS.
    - Provinces with no owner in the DB get DEFAULT_COLOR (#CCCCCC).
    - No text labels are ever added to the SVG.
    - No "unknown" strings are ever inserted into the output.
    """
    owner_map = _get_owner_map(server_id)

    parser = etree.XMLParser(remove_blank_text=False, recover=True)
    tree   = etree.parse(SVG_PATH, parser)
    root   = tree.getroot()

    # Remove sodipodi:namedview — Inkscape page-color metadata that rsvg-convert
    # treats as a white background, washing out province fills.
    for el in list(root):
        if "namedview" in el.tag:
            root.remove(el)

    # Remove unlabeled paths — ~1500 text-glyph / halo paths whose near-white
    # fills sit on top of province fills and make the map appear all-white.
    for el in list(root.iter()):
        if el.tag.split("}")[-1] != "path":
            continue
        if not (el.get(LABEL_ATTR) or "").strip():
            parent = el.getparent()
            if parent is not None:
                parent.remove(el)

    # Fix the viewBox so rsvg-convert renders the actual map area.
    root.set("viewBox", MAP_VIEWBOX)
    root.set("width",  "415mm")
    root.set("height", "240mm")

    for elem in root.iter():
        label = (elem.get(LABEL_ATTR) or "").strip()

        # Skip elements that have no province label or are layer containers.
        if not label or label == "Layer 1":
            continue

        norm_label = _normalize(label)

        # Look up owner — if the label is not in province data, apply default
        # color and move on. Never produce an "unknown" value.
        owner = owner_map.get(norm_label)

        # Debug: log every province → owner resolution
        log.debug("Province: %s  Owner: %s", label, owner)

        if owner is None:
            # Province exists in SVG but has no owner in DB → render as neutral grey
            fill = DEFAULT_COLOR
        else:
            # owner must be a valid country_id; fall back to grey if not in palette
            fill = COUNTRY_COLORS.get(owner, DEFAULT_COLOR)
            if fill == DEFAULT_COLOR and owner not in COUNTRY_COLORS:
                log.warning("Province %s has owner %r which has no color defined", label, owner)

        # Apply hex fill to style attribute; fall back to fill attribute
        style     = elem.get("style", "")
        new_style = _apply_fill(style, fill)
        if new_style != style:
            elem.set("style", new_style)
        elif elem.get("fill") is not None:
            elem.set("fill", fill)

    svg_bytes = etree.tostring(root, xml_declaration=True, encoding="UTF-8")

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
