#!/usr/bin/env python3
"""Generate icon-512.png — brand §6: eclipse motif on navy (#0d1b2a),
one per-product glyph. Marquee's glyph is a venue marquee: a gradient
eclipse ring behind a bulb-lit sign. PIL only; deterministic."""
from PIL import Image, ImageDraw

S = 512
NAVY = (13, 27, 42, 255)
STOPS = [(15, 246, 247), (0, 212, 255), (123, 44, 191)]


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3)) + (255,)


def grad(t):
    return lerp(STOPS[0], STOPS[1], t * 2) if t < 0.5 else \
        lerp(STOPS[1], STOPS[2], (t - 0.5) * 2)


def main():
    img = Image.new("RGBA", (S, S), NAVY)
    d = ImageDraw.Draw(img)
    # Eclipse ring behind the sign.
    ring = [54, 54, 458, 458]
    for i in range(72):
        t = i / 72
        d.arc(ring, start=i * 5, end=i * 5 + 6, fill=grad(t), width=13)
    d.ellipse([126, 126, 386, 386], fill=NAVY)
    # Marquee sign.
    sign = [104, 176, 408, 336]
    d.rounded_rectangle(sign, radius=26, fill=(8, 12, 20, 255),
                        outline=grad(0.25), width=7)
    # Bulbs around the sign.
    bulbs = []
    for x in range(132, 389, 32):
        bulbs.extend([(x, 194), (x, 318)])
    for y in (230, 266, 302):
        bulbs.extend([(122, y), (390, y)])
    for index, (x, y) in enumerate(bulbs):
        r = 9
        d.ellipse([x - r, y - r, x + r, y + r], fill=grad(index / max(1, len(bulbs) - 1)))
    # Ticket silhouette in the sign.
    d.rounded_rectangle([176, 226, 336, 292], radius=12,
                        outline=(254, 254, 254, 255), width=7)
    d.line([(256, 232), (256, 286)], fill=(160, 174, 192, 255), width=4)
    d.ellipse([226, 248, 246, 268], fill=grad(0.55))
    d.ellipse([272, 248, 292, 268], outline=(254, 254, 254, 255), width=5)
    img.save("icon-512.png")
    print("wrote icon-512.png", img.size, img.mode)


if __name__ == "__main__":
    main()
