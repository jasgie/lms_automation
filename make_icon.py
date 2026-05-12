"""
Generates classedge_lms.ico — the app icon for ClassEdge LMS Automation.
Run with:  python make_icon.py
"""
from PIL import Image, ImageDraw, ImageFont
import math, os

# ── Colours (matching lms_app.py) ────────────────────────────────────────────
NAV   = (27,  45,  64)       # #1b2d40  sidebar navy
BLUE  = (26, 115, 232)       # #1a73e8  accent blue
DIM   = (122, 153, 184)      # #7a99b8  dim text
WHITE = (255, 255, 255)
LIGHT = (220, 235, 255)      # light blue tint

def make_frame(size: int) -> Image.Image:
    S = size
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d   = ImageDraw.Draw(img)

    # ── Rounded-rect background ──────────────────────────────────────────────
    r = max(4, S // 8)
    d.rounded_rectangle([0, 0, S-1, S-1], radius=r, fill=NAV)

    # ── Blue accent stripe (bottom quarter) ─────────────────────────────────
    stripe_h = S // 4
    d.rounded_rectangle(
        [0, S - stripe_h, S-1, S-1],
        radius=r, fill=BLUE,
    )
    # fill top corners of stripe so it looks flat on top
    d.rectangle([0, S - stripe_h, S-1, S - stripe_h + r], fill=BLUE)

    # ── Book shape (centre) ──────────────────────────────────────────────────
    bx1 = int(S * 0.18)
    bx2 = int(S * 0.82)
    by1 = int(S * 0.12)
    by2 = int(S * 0.70)
    bw  = bx2 - bx1
    bh  = by2 - by1
    spine_x = bx1 + bw // 2

    # left page
    d.rounded_rectangle([bx1, by1, spine_x, by2], radius=max(2, S//24), fill=LIGHT)
    # right page
    d.rounded_rectangle([spine_x, by1, bx2, by2], radius=max(2, S//24), fill=WHITE)
    # spine line
    lw = max(1, S // 32)
    d.line([spine_x, by1, spine_x, by2], fill=DIM, width=lw)

    # ── Lines on pages (ruled lines illusion) ────────────────────────────────
    if S >= 48:
        margin  = int(S * 0.06)
        line_gap = max(3, bh // 6)
        for i in range(1, 5):
            y = by1 + i * line_gap
            if y >= by2 - lw:
                break
            # left page lines
            d.line([bx1 + margin, y, spine_x - margin, y], fill=DIM, width=max(1, S//64))
            # right page lines
            d.line([spine_x + margin, y, bx2 - margin, y], fill=DIM, width=max(1, S//64))

    # ── Play triangle (bottom-right of book, over blue stripe) ───────────────
    if S >= 32:
        cx = int(S * 0.72)
        cy = int(S * 0.855)
        tr = int(S * 0.10)
        pts = [
            (cx - tr, cy - tr),
            (cx - tr, cy + tr),
            (cx + tr, cy),
        ]
        d.polygon(pts, fill=WHITE)

    # ── "CE" monogram bottom-left of stripe ──────────────────────────────────
    if S >= 64:
        fs = max(8, S // 8)
        try:
            font = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", fs)
        except Exception:
            font = ImageFont.load_default()
        tx = int(S * 0.10)
        ty = S - stripe_h + (stripe_h - fs) // 2 - 1
        d.text((tx, ty), "CE", font=font, fill=WHITE)

    return img


# ── Build all sizes & save ────────────────────────────────────────────────────
sizes  = [16, 24, 32, 48, 64, 128, 256]
frames = [make_frame(s).convert("RGBA") for s in sizes]

out = os.path.join(os.path.dirname(__file__), "classedge_lms.ico")

# PIL ICO: pass all frames as separate RGBA images via append_images.
# The first image sets the primary size; the rest are appended.
frames[0].save(
    out,
    format="ICO",
    append_images=frames[1:],
)
print(f"Icon saved → {out}  ({len(frames)} sizes: {sizes})")
