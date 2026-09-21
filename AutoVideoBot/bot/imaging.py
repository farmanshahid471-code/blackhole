"""
bot/imaging.py
===============
Pillow-based picture helpers.

WHY NOT FFMPEG's drawtext?
--------------------------
`drawtext` needs ffmpeg to be compiled with libfreetype AND it needs a font
file it can find. Several popular ffmpeg builds (including the widely used
static builds) simply do not have it - you get "No such filter: 'drawtext'".

Pillow is a pip package that always works and always finds fonts, so we use
it for the two places where the bot needs to draw letters:

    make_placeholder_card()  a scene whose image failed still gets a frame
    add_title_to_image()     big text over the YouTube thumbnail

Both write a normal image file that ffmpeg then treats like any other still.
"""
from __future__ import annotations

import os
import textwrap
from pathlib import Path

from .utils import debug, ensure_dir, warn

# Common font locations across Windows / macOS / Linux. The first one that
# exists wins; DejaVu ships with Pillow so there is always a final fallback.
FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
]


def find_font(preferred: str | None = None, bold: bool = True) -> str | None:
    """Return a usable .ttf path, or None (Pillow will fall back to its default)."""
    if preferred:
        for cand in (preferred, f"{preferred}.ttf"):
            p = Path(cand)
            if p.exists():
                return str(p)
            for base in ("/usr/share/fonts/truetype/dejavu", "/usr/share/fonts",
                         "C:/Windows/Fonts", "/System/Library/Fonts"):
                p = Path(base) / cand
                if p.exists():
                    return str(p)
    for cand in FONT_CANDIDATES:
        if Path(cand).exists():
            return cand
    # a font the user dropped into assets/fonts/
    local = Path(__file__).resolve().parent.parent / "assets" / "fonts"
    if local.exists():
        for f in sorted(local.iterdir()):
            if f.suffix.lower() in (".ttf", ".otf"):
                return str(f)
    return None


def _font(size: int, preferred: str | None = None):
    from PIL import ImageFont
    path = find_font(preferred)
    try:
        if path:
            return ImageFont.truetype(path, size)
    except Exception as e:
        debug(f"could not load font {path}: {e}")
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _text_size(draw, text: str, font) -> tuple[int, int]:
    try:
        l, t, r, b = draw.textbbox((0, 0), text, font=font)
        return r - l, b - t
    except Exception:
        try:
            return draw.textsize(text, font=font)          # Pillow < 9
        except Exception:
            return len(text) * 10, 20


def make_placeholder_card(out_path: Path, *, width: int, height: int,
                          heading: str = "", body: str = "",
                          bg: tuple[int, int, int] = (13, 17, 23),
                          accent: tuple[int, int, int] = (88, 166, 255),
                          font: str | None = None) -> Path:
    """
    A clean dark card used when an image provider failed for a scene.
    The video still renders, so one bad image never kills the whole project.
    """
    from PIL import Image, ImageDraw
    ensure_dir(Path(out_path).parent)

    img = Image.new("RGB", (width, height), bg)
    draw = ImageDraw.Draw(img)

    # a subtle diagonal gradient so it does not look completely flat
    for y in range(height):
        k = y / max(1, height)
        shade = tuple(int(c + (26 - c) * k * 0.35) for c in bg)
        draw.line([(0, y), (width, y)], fill=shade)

    # accent bar
    bar_h = max(4, height // 180)
    draw.rectangle([int(width * 0.08), int(height * 0.30),
                    int(width * 0.08) + max(60, width // 8), int(height * 0.30) + bar_h],
                   fill=accent)

    if heading:
        f = _font(max(28, int(height * 0.13)), font)
        tw, th = _text_size(draw, heading, f)
        draw.text(((width - tw) // 2, int(height * 0.36)), heading, font=f,
                  fill=(240, 244, 248))

    if body:
        f2 = _font(max(16, int(height * 0.032)), font)
        wrapped = textwrap.fill(body, width=max(24, int(width / (height * 0.020))))
        lines = wrapped.splitlines()[:5]
        y = int(height * 0.56)
        for line in lines:
            tw, th = _text_size(draw, line, f2)
            draw.text(((width - tw) // 2, y), line, font=f2, fill=(154, 164, 178))
            y += int(th * 1.6)

    img.save(out_path, quality=94)
    return out_path


def add_title_to_image(image_path: Path, title: str, *,
                       font: str | None = None,
                       colour: tuple[int, int, int] = (255, 255, 255),
                       outline: tuple[int, int, int] = (0, 0, 0),
                       position: str = "bottom",
                       max_words: int = 5,
                       band: bool = True) -> Path:
    """
    Draw big YouTube-thumbnail text over an existing frame.
    Modifies the file in place and returns its path.
    """
    from PIL import Image, ImageDraw
    p = Path(image_path)
    if not p.exists():
        warn(f"cannot add a title: {p} does not exist")
        return p

    words = str(title).split()[:max_words]
    text = " ".join(words).upper()
    if not text.strip():
        return p

    img = Image.open(p).convert("RGB")
    w, h = img.size
    draw = ImageDraw.Draw(img)

    size = max(28, int(h * 0.13))
    f = _font(size, font)
    wrapped = textwrap.wrap(text, width=max(8, int(w / (size * 0.62))))[:3]

    line_heights = []
    for line in wrapped:
        _tw, th = _text_size(draw, line, f)
        line_heights.append(th)
    total_h = sum(line_heights) + int(size * 0.25) * (len(wrapped) - 1)

    y = h - total_h - int(h * 0.09) if position == "bottom" else int(h * 0.09)

    if band:
        pad = int(h * 0.03)
        box = Image.new("RGBA", img.size, (0, 0, 0, 0))
        bd = ImageDraw.Draw(box)
        bd.rectangle([0, y - pad, w, y + total_h + pad], fill=(0, 0, 0, 130))
        img = Image.alpha_composite(img.convert("RGBA"), box).convert("RGB")
        draw = ImageDraw.Draw(img)

    for line, lh in zip(wrapped, line_heights):
        tw, _ = _text_size(draw, line, f)
        x = (w - tw) // 2
        stroke = max(3, int(size * 0.09))
        try:
            draw.text((x, y), line, font=f, fill=colour,
                      stroke_width=stroke, stroke_fill=outline)
        except TypeError:                       # very old Pillow
            for dx in (-stroke, 0, stroke):
                for dy in (-stroke, 0, stroke):
                    draw.text((x + dx, y + dy), line, font=f, fill=outline)
            draw.text((x, y), line, font=f, fill=colour)
        y += lh + int(size * 0.25)

    img.save(p, quality=94)
    return p


def contact_sheet(images: list[Path], out_path: Path, *, cols: int = 4,
                  thumb_w: int = 480) -> Path | None:
    """
    Build a grid of every scene image. Invaluable while tuning prompts:
    one look tells you if the visual style is consistent across the video.
    """
    from PIL import Image
    paths = [Path(p) for p in images if Path(p).exists()]
    if not paths:
        return None
    ensure_dir(Path(out_path).parent)

    rows = (len(paths) + cols - 1) // cols
    thumb_h = None
    tiles = []
    for p in paths:
        try:
            im = Image.open(p).convert("RGB")
        except Exception:
            continue
        ratio = im.height / max(1, im.width)
        th = int(thumb_w * ratio)
        thumb_h = th
        tiles.append(im.resize((thumb_w, th), Image.LANCZOS))
    if not tiles:
        return None
    thumb_h = thumb_h or tiles[0].height

    sheet = Image.new("RGB", (thumb_w * cols, thumb_h * rows), (12, 12, 14))
    for i, t in enumerate(tiles):
        sheet.paste(t, ((i % cols) * thumb_w, (i // cols) * thumb_h))
    sheet.save(out_path, quality=88)
    return out_path
