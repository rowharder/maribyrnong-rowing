"""Draw the app icons and the link-preview card into site/.

Run once after changing the design:  python3 scripts/make_icons.py
Uses Pillow and the Arial fonts that ship with macOS. The PNGs are committed, so the
hourly build doesn't need to run this.
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SITE = Path(__file__).resolve().parent.parent / "site"
FONTS = Path("/System/Library/Fonts/Supplemental")

# Colours from site/styles.css
ACCENT = "#00428b"
PAGE = "#f9f9f7"
INK = "#0b0b0b"
INK_2 = "#52514e"
GREEN, AMBER, RED = "#0ca30c", "#fab219", "#d03b3b"
HOUSING = "#002a5c"  # darker accent behind the lights
WATER = "#2f6db5"

SCALE = 4  # draw big, then shrink, for smooth edges


def lights(draw, cx, top, d, gap):
    """A traffic-light housing with red, amber and green lights, top to bottom."""
    pad = d * 0.22
    h = 3 * d + 2 * gap
    draw.rounded_rectangle([cx - d / 2 - pad, top - pad, cx + d / 2 + pad, top + h + pad],
                           radius=d / 2 + pad, fill=HOUSING)
    for i, colour in enumerate((RED, AMBER, GREEN)):
        y = top + i * (d + gap)
        draw.ellipse([cx - d / 2, y, cx + d / 2, y + d], fill=colour)


def wave(draw, x0, x1, y, amp, width, colour):
    """A gentle wave band across the bottom (the river), drawn as one filled shape."""
    import math
    xs = [x0 + (x1 - x0) * i / 200 for i in range(201)]
    mid = [y + amp * math.sin(i / 200 * 4 * math.pi) for i in range(201)]
    top = [(x, m - width / 2) for x, m in zip(xs, mid)]
    bottom = [(x, m + width / 2) for x, m in zip(reversed(xs), reversed(mid))]
    draw.polygon(top + bottom, fill=colour)
    for x, m in ((xs[0], mid[0]), (xs[-1], mid[-1])):  # round ends
        draw.ellipse([x - width / 2, m - width / 2, x + width / 2, m + width / 2], fill=colour)


def icon(size, path):
    """Square icon. Full-bleed background, so it also works as an Android 'maskable' icon
    (the lights stay inside the middle 80% safe zone)."""
    s = size * SCALE
    img = Image.new("RGB", (s, s), ACCENT)
    draw = ImageDraw.Draw(img)
    d = s * 0.17
    gap = s * 0.045
    top = s * 0.17
    lights(draw, s / 2, top, d, gap)
    wave(draw, s * 0.12, s * 0.88, s * 0.86, s * 0.018, s * 0.035, WATER)
    img.resize((size, size), Image.LANCZOS).save(path, optimize=True)


def card(path):
    """1200x630 link preview for WhatsApp, Facebook, Messenger, iMessage etc."""
    w, h = 1200 * 2, 630 * 2
    img = Image.new("RGB", (w, h), PAGE)
    draw = ImageDraw.Draw(img)
    bold = lambda px: ImageFont.truetype(str(FONTS / "Arial Bold.ttf"), px * 2)
    regular = lambda px: ImageFont.truetype(str(FONTS / "Arial.ttf"), px * 2)

    # Right-hand panel: the icon artwork, large.
    panel_x = w * 0.68
    draw.rectangle([panel_x, 0, w, h], fill=ACCENT)
    pw = w - panel_x
    d = h * 0.17
    lights(draw, panel_x + pw / 2, h * 0.11, d, h * 0.045)
    wave(draw, panel_x + pw * 0.12, w - pw * 0.12, h * 0.87, h * 0.02, h * 0.03, WATER)

    x = 72 * 2
    draw.text((x, 92 * 2), "Maribyrnong", font=bold(74), fill=INK)
    draw.text((x, 176 * 2), "Rowing Conditions", font=bold(74), fill=INK)
    draw.text((x, 290 * 2), "Go, caution or no go for every", font=regular(36), fill=INK_2)
    draw.text((x, 336 * 2), "session, four days ahead.", font=regular(36), fill=INK_2)
    # Small coloured dots before the factor list, echoing the page's lights.
    y = 440 * 2
    for i, colour in enumerate((GREEN, AMBER, RED)):
        cx = x + 14 * 2 + i * 34 * 2
        draw.ellipse([cx - 14 * 2, y, cx + 14 * 2, y + 28 * 2], fill=colour)
    draw.text((x + 112 * 2, y - 2 * 2), "Wind · Rain · Flow · Tide · Fog", font=regular(30), fill=INK_2)
    draw.text((x, 530 * 2), "From BOM and Melbourne Water", font=regular(26), fill=INK_2)
    img.resize((1200, 630), Image.LANCZOS).save(path, optimize=True)


if __name__ == "__main__":
    icon(512, SITE / "icon-512.png")
    icon(192, SITE / "icon-192.png")
    icon(180, SITE / "apple-touch-icon.png")
    icon(32, SITE / "favicon-32.png")
    card(SITE / "og-image.png")
    print("Wrote icons and og-image.png to site/")
