"""
PWA ikonlarini uretir.

Web uygulamasini Android ana ekranina yukleyebilmek icin 192x192 ve
512x512 PNG ikonlar gerekiyor. Elle cizilmis degil; burada kod ile
uretiliyor ve `web/static/` altina yaziliyor.

Kullanim:
    python tools/make_icons.py
"""
from __future__ import annotations

import os
import sys

from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "web", "static")

# Uygulamanin koyu temasiyla uyumlu.
BG = (11, 18, 28)
BG_DEEP = (16, 26, 40)
UP = (74, 222, 128)      # yesil mum
DOWN = (255, 107, 107)   # kirmizi mum
LINE = (90, 140, 200)
TEXT = (223, 232, 241)


def draw_candles(d: ImageDraw.ImageDraw, cx: float, cy: float,
                 w: int, h: int, n: int = 9) -> None:
    """Klasik mum grafigi: bir kismi yukselen, bir kismi dusen."""
    # Pillow cizim komutlari TAM SAYI koordinat istiyor; butun olcekler
    # en basta int'e cevrilir (yoksa TypeError: 'float' object ...).
    cx, cy, w, h = int(cx), int(cy), int(w), int(h)
    # Govde dar, fit belirgin olsun: ikon kucuk boyutta da okunmali.
    body = max(2, int(w * 0.26))
    step = w / (n - 1)
    bot = cy + h // 2

    # Fiyat yolu: once yukselis, sonra kucuk bir duusus.
    # (normalize edilmis 0..1, 0 = dip, 1 = zirve)
    path = [0.22, 0.40, 0.31, 0.54, 0.63, 0.79, 0.90, 0.72, 0.60]

    prev_x = prev_y = None
    for i in range(n):
        x = int(cx - w / 2 + i * step)
        p = path[i]
        y = int(bot - p * h)
        rising = i == 0 or path[i] >= path[i - 1]
        col = UP if rising else DOWN

        # Govdenin ustunden bir onceki kapanisa cizgi (trend hissi)
        if prev_x is not None:
            d.line([prev_x, prev_y, x, y], fill=LINE, width=max(1, w // 55))

        # fit: govdenin belirgin sekilde disina tasar
        wick_top = int(y - h * 0.16)
        wick_bot = int(y + h * 0.13)
        d.rectangle([x - max(1, w // 110), wick_top, x + max(1, w // 110),
                     wick_bot], fill=col)

        # govde
        oy = int(y - h * 0.055)
        d.rectangle([x - body // 2, oy, x + body // 2,
                     int(oy + h * 0.11)], fill=col)

        prev_x, prev_y = x, y


def make_icon(size: int) -> Image.Image:
    img = Image.new("RGB", (size, size), BG)
    d = ImageDraw.Draw(img)

    # Dikey degrade: arka plan biraz acilir.
    for y in range(size):
        t = y / max(1, size - 1)
        d.line([0, y, size, y],
               fill=tuple(int(BG[i] + (BG_DEEP[i] - BG[i]) * t) for i in range(3)))

    s = size / 512.0

    # Ince cerceve
    d.rounded_rectangle([int(6 * s), int(6 * s), int(size - 6 * s),
                         int(size - 6 * s)],
                        radius=int(86 * s), outline=(40, 60, 85),
                        width=max(1, int(3 * s)))

    draw_candles(d, cx=size / 2, cy=size / 2 - 34 * s, w=352 * s, h=250 * s)

    # Altta "TA" yazisi
    try:
        from PIL import ImageFont
        font = ImageFont.truetype("arialbd.ttf", int(92 * s))
    except Exception:
        font = None
    label = "TA"
    if font is not None:
        bb = d.textbbox((0, 0), label, font=font)
        tw, th = bb[2] - bb[0], bb[3] - bb[1]
        d.text((size / 2 - tw / 2, size - 130 * s), label, font=font,
               fill=TEXT)
    else:
        d.text((size / 2 - 26 * s, size - 96 * s), label, fill=TEXT)

    return img


def main() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)
    made = []
    for size, name in ((192, "icon-192.png"), (512, "icon-512.png"),
                       (180, "apple-touch-icon.png")):
        path = os.path.join(OUT_DIR, name)
        make_icon(size).save(path, "PNG", optimize=True)
        made.append((name, size))

    # Maskable: Android 8+ ikonu sistem maskeleriyle kirpilir.
    # Guvenli alan %80 oldugu icin grafigi biraz kucultuyoruz.
    mk = make_icon(512)
    canvas = Image.new("RGB", (512, 512), BG)
    canvas.paste(mk.crop((60, 60, 452, 452)).resize((392, 392), Image.LANCZOS),
                 (60, 60))
    mask_path = os.path.join(OUT_DIR, "icon-maskable-512.png")
    canvas.save(mask_path, "PNG", optimize=True)
    made.append(("icon-maskable-512.png", 512))

    for name, size in made:
        p = os.path.join(OUT_DIR, name)
        print(f"  {name:26s} {size}x{size}  {os.path.getsize(p):>7d} bayt")
    return 0


if __name__ == "__main__":
    sys.exit(main())