"""Render a to-scale visual mock of the implemented Conviction Mode card (lib/main.dart) with
live AGA.V values, so the layout/clutter can be reviewed. Mirrors the real widget theme.
Not used by the app — a design preview only. Run: python tools_preview_conviction.py"""
from PIL import Image, ImageDraw, ImageFont

S = 2  # supersample for crispness
W, H = 760 * S, 1180 * S
BG = (0, 0, 0)
PANEL = (10, 10, 11)
BORDER = (36, 36, 36)
ACCENT = (217, 164, 65)     # kAccent amber
DIM = (191, 191, 191)       # kDim
FAINT = (112, 112, 112)     # kFaint
CYAN = (126, 140, 160)      # kCyan steel
PURPLE = (156, 123, 176)    # Q pillar
RED = (200, 90, 82)         # kRed
ORANGE = (210, 150, 70)
WHITE = (235, 235, 235)
TRACK = (20, 20, 20)
PRICE_BG = (21, 18, 10)     # faint amber-tinted anchor row

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

def stripe(x, y0, y1, color):
    d.rectangle([x * S, y0 * S, (x + 3) * S, y1 * S], fill=color)

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
text(28, y + 10, "AGA.V", font(15, True), WHITE)
text(28, y + 32, "OPTION CONVEXITY · I", font(8), FAINT)
text(732, y + 6, "7.9", font(30, True), ACCENT, anchor="ra")
text(732, y + 40, "STRONG ASYMMETRY", font(9, True), ACCENT, anchor="ra")
text(732, y + 54, "± 1.0 · full data", font(8), FAINT, anchor="ra")
d.line([(cx0 * S, (y + 70) * S), (cx1 * S, (y + 70) * S)], fill=BORDER, width=1 * S)
text(28, y + 80, "BELOW FLOOR — ACCUMULATE · watch closely", font(11, True), ACCENT)

py = y + 104
def pillar(py, label, score, color, frac, detail):
    text(28, py, label, font(10, True), DIM)
    text(732, py, f"{score:.1f}", font(11, True), color, anchor="ra")
    bar(28, py + 16, 704, frac, color)
    text(28, py + 24, detail, font(8), FAINT)
    return py + 44

py = pillar(py, "MACRO TAILWIND", 6.7, CYAN, 0.67, "MRI 40 · α +0.40 · tailwind")
py = pillar(py, "COMPANY QUALITY", 7.5, PURPLE, 0.754, "JSF 3.5/4 · resource 0.74 · mgmt 0.61")
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
py = pillar(py, "VALUATION ASYMMETRY", 8.8, ACCENT, 0.88,
            "up +222%  vs  0% to floor  ·  payoff 27x  ·  catalyst +17%")

# ladder (PRICE row highlighted as the anchor)
ly = py + 4
rect(28, ly, 732, ly + 104, outline=BORDER, fill=BG)
ladder = [("BULL", "2.284", "+222% upside · cat-adj", ACCENT, False),
          ("BASE", "1.690", "base case", DIM, False),
          ("PRICE", "0.710", "live", WHITE, True),
          ("BEAR", "1.050", "stress", ORANGE, False),
          ("FLOOR", "0.824", "price 16% BELOW floor", CYAN, False)]
lyy = ly + 6
for name, val, note, col, hi in ladder:
    if hi:
        d.rectangle([32 * S, (lyy - 2) * S, 728 * S, (lyy + 15) * S], fill=PRICE_BG)
    fnt = font(10, True) if hi else font(10)
    text(40, lyy, name, fnt, col)
    text(150, lyy, val, fnt, WHITE if hi else DIM)
    text(720, lyy, note, font(9), FAINT, anchor="ra")
    lyy += 19
# recent catalysts strip (Phase 8)
cy = ly + 104 + 8
rect(28, cy, 732, cy + 70, outline=BORDER, fill=BG)
text(40, cy + 6, "RECENT CATALYSTS", font(7), FAINT)
cats = [(ACCENT, "Red Mountain: 1,240 g/t AgEq over 4.2m", "7d"),
        (ACCENT, "Plan of Operations accepted for review", "21d"),
        (ACCENT, "Updated PEA scoped; recoveries >88% Ag", "55d")]
cyy = cy + 22
for dot, label, age in cats:
    d.ellipse([42 * S, (cyy + 2) * S, 48 * S, (cyy + 8) * S], fill=dot)
    text(56, cyy, label, font(9), DIM)
    text(720, cyy, age, font(8), FAINT, anchor="ra")
    cyy += 15
card_bot = cy + 70 + 8
rect(cx0, card_top, cx1, card_bot, outline=BORDER)
stripe(cx0, card_top, card_bot, ACCENT)   # left accent stripe keyed to rating

# ============================ GMX.TO (ranked) ============================
y = card_bot + 10
gtop = y
text(28, y + 10, "GMX.TO", font(13, True), WHITE)
text(28, y + 30, "COMMODITY CYCLICAL · III", font(8), FAINT)
text(732, y + 8, "3.9", font(24, True), ORANGE, anchor="ra")
text(732, y + 36, "WEAK / EXPENSIVE", font(9, True), ORANGE, anchor="ra")
text(28, y + 56, "UPSIDE SPENT — HOLD / TRIM", font(10, True), ORANGE)
text(28, y + 74, "T 5.2   ·   Q 4.8   ·   V 2.4        up +8%  vs  46% to floor", font(9), FAINT)
gbot = y + 96
rect(cx0, gtop, cx1, gbot, outline=BORDER)
stripe(cx0, gtop, gbot, ORANGE)

# ============================ BAD.V (forensic gate demo) ============================
y = gbot + 10
btop = y
text(28, y + 10, "BAD.V", font(13, True), WHITE)
text(28, y + 30, "OPTION CONVEXITY · I", font(8), FAINT)
text(732, y + 8, "4.0", font(24, True), RED, anchor="ra")
text(732, y + 36, "WEAK / EXPENSIVE", font(9, True), RED, anchor="ra")
text(28, y + 56, "FORENSIC DECAY — AVOID / DE-RISK", font(10, True), RED)
# gate flag chip
chip = "GATE · JSF 1.0 < 1.5; dilution 30%/yr"
cw = int(d.textlength(chip, font=font(8)) / S) + 12
rect(28, y + 74, 28 + cw, y + 90, outline=(120, 60, 55))
text(34, y + 78, chip, font(8), RED)
bbot = y + 100
rect(cx0, btop, cx1, bbot, outline=BORDER)
stripe(cx0, btop, bbot, RED)

# footer
text(20, bbot + 14, "Assessment-only. Position caps, ES95 throttle, covariance shrinkage and", font(8), FAINT)
text(20, bbot + 26, "Kelly de-leveraging are excluded here — open Detailed Analysis for those.", font(8), FAINT)

img = img.resize((W // S, H // S), Image.LANCZOS)
img.save("conviction_card_preview.png")
print("wrote conviction_card_preview.png", img.size)
