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

MAP_VIEWBOX = "65 -5 415 240"

RSVG_CONVERT = "/nix/store/9gwwn0yb3zj0vr1rn6ix2bia57ahksry-librsvg-2.60.0/bin/rsvg-convert"

# country_id -> hex color  (SVG rendering ONLY — never use color names here)
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

# country_id -> display name  (Discord embed / legend ONLY — not used in SVG)
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

# country_id -> plain color name  (Discord embed / legend ONLY — not used in SVG)
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

DEFAULT_COLOR = "#CCCCCC"

INKSCAPE_NS = "http://www.inkscape.org/namespaces/inkscape"
LABEL_ATTR  = f"{{{INKSCAPE_NS}}}label"

# Strips fill and fill-opacity out of a CSS style string so the fill
# attribute takes full effect (style always wins over attribute in SVG).
_STRIP_FILL_RE         = re.compile(r"(?<![a-zA-Z-])fill\s*:[^;]+;?")
_STRIP_FILL_OPACITY_RE = re.compile(r"fill-opacity\s*:[^;]+;?")


def _strip_fill_from_style(style: str) -> str:
    """Remove fill and fill-opacity declarations from a CSS style string."""
    style = _STRIP_FILL_RE.sub("", style)
    style = _STRIP_FILL_OPACITY_RE.sub("", style)
    # tidy up any double semicolons left behind
    style = re.sub(r";{2,}", ";", style).strip(";").strip()
    return style


def _normalize(s: str) -> str:
    return s.strip().lower().replace(" ", "")


def _get_province_dict(server_id: str) -> dict[str, dict]:
    """
    Return {normalized_province_name: {"owner": country_id}} for every
    province row belonging to this server.  The key matches the
    inkscape:label values in the SVG (e.g. 'rhineland001').
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT province_name, owner_country FROM provinces "
        "WHERE server_id=? AND scenario_id=?",
        (server_id, SCENARIO_ID),
    ).fetchall()
    conn.close()

    province_dict: dict[str, dict] = {}
    for r in rows:
        key = _normalize(r["province_name"])
        province_dict[key] = {"owner": r["owner_country"]}
    return province_dict


def render_map_png(output_width: int = 1400, server_id: str = "guild_demo") -> bytes:
    """
    Color every province in the SVG by its current owner and return PNG bytes.

    Coloring rules (SVG only — never use color names):
    - element.set("fill", hex_color)   ← only this API is used
    - fill/fill-opacity are stripped from style so the fill attribute wins
    - Unmatched provinces → DEFAULT_COLOR (#CCCCCC), no label added
    - No <text> elements are ever inserted
    """
    province_dict = _get_province_dict(server_id)

    parser = etree.XMLParser(remove_blank_text=False, recover=True)
    tree   = etree.parse(SVG_PATH, parser)
    root   = tree.getroot()

    # Remove sodipodi:namedview — Inkscape page-color metadata that
    # rsvg-convert treats as a white page background, washing out fills.
    for el in list(root):
        if "namedview" in el.tag:
            root.remove(el)

    # Remove unlabeled paths — ~1500 text-glyph / halo paths with near-white
    # fills that sit on top of province fills and make the map appear white.
    for el in list(root.iter()):
        if el.tag.split("}")[-1] != "path":
            continue
        if not (el.get(LABEL_ATTR) or "").strip():
            parent = el.getparent()
            if parent is not None:
                parent.remove(el)

    # Fix viewBox so rsvg-convert renders the actual map area.
    root.set("viewBox", MAP_VIEWBOX)
    root.set("width",  "415mm")
    root.set("height", "240mm")

    # ── Color every province element ───────────────────────────────────────
    for element in root.iter():
        # Province paths are identified by their inkscape:label value.
        svg_id = (element.get(LABEL_ATTR) or "").strip()

        if not svg_id or svg_id == "Layer 1":
            continue

        province = province_dict.get(_normalize(svg_id))

        if province is None:
            # Label exists in SVG but not in province data → neutral grey
            element.set("fill", DEFAULT_COLOR)
            # Strip fill from style so the attribute actually takes effect
            style = element.get("style", "")
            if style:
                element.set("style", _strip_fill_from_style(style))
            continue

        owner = province.get("owner")
        color = COUNTRY_COLORS.get(owner, DEFAULT_COLOR) if owner else DEFAULT_COLOR

        # Debug: confirm every mapping before it is applied
        print(f"SVG: {svg_id!r}  Owner: {owner!r}  Color: {color}")

        # CRITICAL: strip fill out of style so element.set("fill") wins
        style = element.get("style", "")
        if style:
            element.set("style", _strip_fill_from_style(style))

        # Set fill attribute directly — hex only, never a color name
        element.set("fill", color)

    # ── Render to PNG via rsvg-convert ────────────────────────────────────
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
