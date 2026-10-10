"""Outline "ara." in Instrument Serif Italic as SVG paths (wordmark, mark and favicon).

Shaped with HarfBuzz so the font's own kerning applies, then tracked by -0.02em with the dot
pulled in another -0.02em, matching the approved candidate B on the wordmark sheet.
"""

import sys
from pathlib import Path

import uharfbuzz as hb
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

font_path, out_dir = Path(sys.argv[1]), Path(sys.argv[2])
out_dir.mkdir(parents=True, exist_ok=True)

ttf = TTFont(font_path)
glyphs = ttf.getGlyphSet()
upem = ttf["head"].unitsPerEm
blob = hb.Blob(font_path.read_bytes())
face = hb.Face(blob)
font = hb.Font(face)
order = ttf.getGlyphOrder()

TRACK = -0.02 * upem
DOT_PULL = -0.02 * upem


def outline(text: str, track: float = TRACK):
    buf = hb.Buffer()
    buf.add_str(text)
    buf.guess_segment_properties()
    hb.shape(font, buf, {"kern": True, "liga": True})
    x = 0.0
    paths, bounds = [], None
    for index, (info, pos) in enumerate(zip(buf.glyph_infos, buf.glyph_positions)):
        name = order[info.codepoint]
        char = text[info.cluster]
        if char == ".":
            x += DOT_PULL
        # Font units are y-up; SVG is y-down.
        transform = (1, 0, 0, -1, x + pos.x_offset, -pos.y_offset)
        pen = SVGPathPen(glyphs)
        glyphs[name].draw(TransformPen(pen, transform))
        paths.append(pen.getCommands())
        bpen = BoundsPen(glyphs)
        glyphs[name].draw(TransformPen(bpen, transform))
        if bpen.bounds:
            b = bpen.bounds
            bounds = b if bounds is None else (
                min(bounds[0], b[0]), min(bounds[1], b[1]), max(bounds[2], b[2]), max(bounds[3], b[3])
            )
        x += pos.x_advance + (track if index < len(buf.glyph_infos) - 1 else 0)
    return " ".join(paths), bounds


def fmt(v: float) -> str:
    return f"{v:.1f}".rstrip("0").rstrip(".")


def svg(text: str, label: str, pad_ratio: float = 0.04) -> str:
    d, (x0, y0, x1, y1) = outline(text)
    pad = upem * pad_ratio
    vb = (x0 - pad, y0 - pad, (x1 - x0) + 2 * pad, (y1 - y0) + 2 * pad)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{" ".join(fmt(v) for v in vb)}" '
        f'role="img" aria-label="{label}"><path fill="currentColor" d="{d}"/></svg>\n'
    ), vb, d


wordmark, wvb, _ = svg("ara.", "ara.")
mark, mvb, mark_d = svg("a.", "ara.")
(out_dir / "ara-wordmark.svg").write_text(wordmark)
(out_dir / "ara-mark.svg").write_text(mark)

# Favicon: the "a." mark on a rounded ink square; inverted when the browser chrome is dark.
size = 64
radius = 14
w, h = mvb[2], mvb[3]
scale = (size * 0.74) / max(w, h)
tx = (size - w * scale) / 2 - mvb[0] * scale
ty = (size - h * scale) / 2 - mvb[1] * scale
favicon = (
    f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}">'
    "<style>.bg{fill:#171717}.fg{fill:#fafafa}"
    "@media (prefers-color-scheme: dark){.bg{fill:#fafafa}.fg{fill:#171717}}</style>"
    f'<rect class="bg" width="{size}" height="{size}" rx="{radius}"/>'
    f'<path class="fg" transform="translate({fmt(tx)} {fmt(ty)}) scale({scale:.5f})" d="{mark_d}"/>'
    "</svg>\n"
)
(out_dir / "favicon.svg").write_text(favicon)
print("upem", upem, "wordmark viewBox", [fmt(v) for v in wvb], "aspect", round(wvb[2] / wvb[3], 3))
print("mark viewBox", [fmt(v) for v in mvb])
for name in ("ara-wordmark.svg", "ara-mark.svg", "favicon.svg"):
    print(name, (out_dir / name).stat().st_size, "bytes")
