"""Render a to-scale visual mock of the implemented Conviction Mode card (lib/main.dart) with
live AGA.V values, so the layout/clutter can be reviewed. Mirrors the real widget theme.
Not used by the app — a design preview only. Run: python tools_preview_conviction.py"""
from PIL import Image, ImageDraw, ImageFont

S = 2  # supersample for crispness
W, H = 760 * S, 1120 * S
BG = (0, 0, 0)
PANEL = (10, 10, 11)
BORDER = (36, 36, 36)
ACCENT = (217, 164, 65)     # kAccent amber
DIM = (191, 191, 191)       # kDim
FAINT = (112, 112, 112)     # kFaint
CYAN = (126, 140, 160)      # kCyan steel
PURPLE = (156, 123, 176)    # Q pillar
RED = (200, 90, 82)         # kRed
WHITE = (235, 235, 235)
TRACK = (20, 20, 20)

F = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
FB = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"
def font(sz, bold=False):
    return ImageFont.truetype(FB if bold else F, sz * S)

img = Image.new("RGB", (W, H), BG)
d = ImageDraw.Draw(img)

def text(x, y, s, fnt, fill, anchor="la"):
    d.text((x * S, y * S), s, font=fnt, fill=fill, anchor=anchor)

def rect(x0, y0, x1, y1, outline=None, fill=None, wd=1, r=3):
    d.rounded_rectangle([x0 * S, y0 * S, x1 * S, y1 * S], radius=r * S,
                        outline=outline, fill=fill, width=wd * S)

def bar(x, y, w, frac, color, h=4):
    rect(x, y, x + w, y + h, fill=TRACK, r=2)
    if frac > 0:
        rect(x, y, x + w * max(0.02, min(1, frac)), y + h, fill=color, r=2)

# ── view toggle ──
text(20, 16, "CONVICTION MODE", font(11, True), ACCENT)
d.line([(20 * S, 34 * S), (190 * S, 34 * S)], fill=ACCENT, width=2 * S)
text(220, 16, "DETAILED ANALYSIS", font(11, True), FAINT)
d.line([(0, 36 * S), (W, 36 * S)], fill=BORDER, width=1 * S)

# ── regime header strip ──
y = 50
rect(14, y, 746, y + 44, outline=BORDER, fill=PANEL)
text(28, y + 8, "FOCUS", font(7), FAINT)
text(28, y + 20, "WATCH A FEW · CLOSELY", font(11, True), DIM)
text(300, y + 8, "REGIME", font(7), FAINT)
text(300, y + 20, "RISK-ON · MRI 40", font(11, True), ACCENT)
text(560, y + 8, "TOP CONVICTION", font(7), FAINT)
text(560, y + 20, "AGA.V", font(11, True), ACCENT)

# ============================ AGA.V CARD ============================
cx0, cx1 = 14, 746
y = 108
card_top = y
# header band
text(28, y + 10, "AGA.V", font(15, True), WHITE)
text(28, y + 32, "OPTION CONVEXITY · I", font(8), FAINT)
text(732, y + 6, "7.8", font(30, True), ACCENT, anchor="ra")
text(732, y + 16, "/10", font(11), FAINT, anchor="la") if False else None
text(732, y + 40, "STRONG ASYMMETRY", font(9, True), ACCENT, anchor="ra")
text(732, y + 54, "± 1.0 · full data", font(8), FAINT, anchor="ra")
d.line([(cx0 * S, (y + 70) * S), (cx1 * S, (y + 70) * S)], fill=BORDER, width=1 * S)
# directive
text(28, y + 80, "BELOW FLOOR — ACCUMULATE · watch closely", font(11, True), ACCENT)

# pillars
py = y + 104
def pillar(py, rank_label, score, color, frac, detail):
    text(28, py, rank_label, font(10, True), DIM)
    text(732, py, f"{score:.1f}", font(11, True), color, anchor="ra")
    bar(28, py + 16, 704, frac, color)
    text(28, py + 24, detail, font(8), FAINT)
    return py + 44

py = pillar(py, "MACRO TAILWIND", 6.7, CYAN, 0.67, "MRI 40 · α +0.40 · tailwind")
py = pillar(py, "COMPANY QUALITY", 7.5, PURPLE, 0.754, "JSF 3.5/4 · resource 0.74 · mgmt 0.61")
# lens chips
chips = [("GRADE", 0.74), ("SCALE", 1.00), ("JURIS", 0.76), ("METAL", 0.71), ("PERMIT", 0.45)]
chx = 28
for label, v in chips:
    col = ACCENT if v >= 0.66 else (DIM if v >= 0.45 else FAINT)
    s = f"{label} {v:.2f}"
    w = int(d.textlength(s, font=font(8)) / S) + 12
    rect(chx, py - 4, chx + w, py + 14, outline=BORDER)
    text(chx + 6, py, s, font(8), col)
    chx += w + 6
py += 26
py = pillar(py, "VALUATION ASYMMETRY", 8.7, ACCENT, 0.87,
            "up +175%  vs  0% to floor  ·  payoff 17.5x")

# ladder
ly = py + 4
rect(28, ly, 732, ly + 104, outline=BORDER, fill=BG)
ladder = [("BULL", "1.950", "+175% upside", ACCENT),
          ("BASE", "1.690", "base case", DIM),
          ("> PRICE", "0.710", "live", WHITE),
          ("BEAR", "1.050", "stress", (210, 150, 70)),
          ("FLOOR", "0.824", "price 16% BELOW floor", CYAN)]
lyy = ly + 8
for name, val, note, col in ladder:
    text(40, lyy, name, font(10), col)
    text(150, lyy, val, font(10), DIM)
    text(720, lyy, note, font(9), FAINT, anchor="ra")
    lyy += 19
card_bot = ly + 104 + 8
rect(cx0, card_top, cx1, card_bot, outline=(120, 92, 40), wd=1)

# ============================ GMX.TO (ranked below) ============================
y = card_bot + 10
gtop = y
text(28, y + 10, "GMX.TO", font(13, True), WHITE)
text(28, y + 30, "COMMODITY CYCLICAL · III", font(8), FAINT)
text(732, y + 8, "3.9", font(24, True), (210, 150, 70), anchor="ra")
text(732, y + 36, "WEAK / EXPENSIVE", font(9, True), (210, 150, 70), anchor="ra")
text(28, y + 56, "UPSIDE SPENT — HOLD / TRIM", font(10, True), (210, 150, 70))
text(28, y + 74, "T 5.2   ·   Q 4.8   ·   V 2.4        up +8%  vs  46% to floor", font(9), FAINT)
rect(cx0, gtop, cx1, y + 96, outline=BORDER)

# footer
text(20, y + 110, "Assessment-only. Position caps, ES95 throttle, covariance shrinkage and", font(8), FAINT)
text(20, y + 122, "Kelly de-leveraging are excluded here — open Detailed Analysis for those.", font(8), FAINT)

img = img.resize((W // S, H // S), Image.LANCZOS)
img.save("conviction_card_preview.png")
print("wrote conviction_card_preview.png", img.size)
