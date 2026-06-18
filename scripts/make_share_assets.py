#!/usr/bin/env python3
"""Generate the social share image (og-image.png) and PWA app icons (icon-192/512)
from the MAS monogram, in the brand colours. Re-runnable; writes to the repo root.

    python3 scripts/make_share_assets.py
"""
import os, io
import cairosvg
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MONO = os.path.join(ROOT, 'src', 'assets', 'monogram-white.svg')

REFLEX = (14, 30, 145)        # #0E1E91
G_TOP = (28, 98, 183)         # #1C62B7
G_MID = (14, 30, 145)         # #0E1E91
G_BOT = (22, 46, 104)         # #162E68
WHITE = (255, 255, 255)
SOFT = (205, 214, 245)        # subtitle tint

# Candidate font paths, tried in order: macOS first, then common Linux (CI) locations,
# so the OG image renders with real type on a GitHub runner instead of the tiny
# bitmap default. The first that loads wins.
FONT_BOLD = ['/System/Library/Fonts/Supplemental/Arial Bold.ttf',
             '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
             '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf']
FONT_REG = ['/System/Library/Fonts/Supplemental/Arial.ttf',
            '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
            '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf']


def mono_png(px):
    """White monogram, transparent background, px by px."""
    data = cairosvg.svg2png(url=MONO, output_width=px, output_height=px, background_color='transparent')
    return Image.open(io.BytesIO(data)).convert('RGBA')


def vgrad(w, h, top, mid, bot):
    img = Image.new('RGB', (w, h))
    px = img.load()
    for y in range(h):
        t = y / (h - 1)
        if t < 0.5:
            u = t / 0.5; c = tuple(round(top[i] + (mid[i] - top[i]) * u) for i in range(3))
        else:
            u = (t - 0.5) / 0.5; c = tuple(round(mid[i] + (bot[i] - mid[i]) * u) for i in range(3))
        for x in range(w):
            px[x, y] = c
    return img


def font(paths, size):
    for p in ([paths] if isinstance(paths, str) else paths):
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue
    return ImageFont.load_default()


def og_image():
    W, H = 1200, 630
    img = vgrad(W, H, G_TOP, G_MID, G_BOT).convert('RGBA')
    d = ImageDraw.Draw(img)
    # monogram, left, vertically centred
    m = mono_png(320)
    img.alpha_composite(m, (96, (H - 320) // 2))
    # text block
    x = 470
    d.text((x, 196), 'WORLD CUP 2026', font=font(FONT_BOLD, 78), fill=WHITE)
    d.text((x, 286), 'Probability Centre', font=font(FONT_BOLD, 46), fill=WHITE)
    d.line([(x + 2, 360), (x + 470, 360)], fill=(120, 150, 230), width=2)
    d.text((x, 384), 'Live title odds · 10,000-run Monte Carlo', font=font(FONT_REG, 30), fill=SOFT)
    d.text((x, 430), 'Family predictions league · live scores', font=font(FONT_REG, 30), fill=SOFT)
    d.text((x, 500), 'mosabs2.github.io/worldcup-2026', font=font(FONT_BOLD, 26), fill=(150, 175, 240))
    img.convert('RGB').save(os.path.join(ROOT, 'og-image.png'))
    return 'og-image.png 1200x630'


def icon(px):
    """Maskable-safe: rounded blue field, white monogram in the central safe zone."""
    img = Image.new('RGBA', (px, px), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = round(px * 0.18)
    d.rounded_rectangle([0, 0, px - 1, px - 1], radius=r, fill=REFLEX + (255,))
    ms = round(px * 0.62)               # ~62% keeps the mark inside the maskable safe zone
    m = mono_png(ms)
    img.alpha_composite(m, ((px - ms) // 2, (px - ms) // 2))
    img.save(os.path.join(ROOT, f'icon-{px}.png'))
    return f'icon-{px}.png'


if __name__ == '__main__':
    out = [og_image(), icon(512), icon(192)]
    print('wrote: ' + ', '.join(out))
