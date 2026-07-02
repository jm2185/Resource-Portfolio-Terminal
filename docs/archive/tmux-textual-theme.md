> **Provenance.** Design spec exported from Claude Design
> (`commodityex-cockpit-design-system`, `guidelines/tmux-textual-theme.md`).
>
> **Implementation status — APPLIED.** The refined theme below is live in
> `commodityex_tui.py`:
> - the `Cockpit.CSS` block was *merged* (not pasted-over) so every functional
>   selector is preserved — Footer dim, rail padding `1 1`, the `.convictioncard`
>   round-border + amber left-rule, `.compactrow`/`.live`, and `Button.-run`.
> - the glow stand-in is wired: `.live` is toggled onto the focused conviction
>   card by the existing 2 Hz `_pulse`.
> - the Rich-markup helpers ship as `_pillar()` / `_badge()` / `_rating()` and
>   render the focused-name conviction card (T/Q/V PillarBars, the JSF-gate
>   Badge, the hero ConvictionRating). `_spark()` / `_range_bar()` already existed.
>
> Treat the web kit as the high-fidelity spec; this file is its character-grid
> projection. Edit the code, not a literal paste of the block below.

---

# Cockpit ↔ tmux / Textual — translation guide

**TL;DR — it already fits.** Every color in this design system was lifted
verbatim from `commodityex_tui.py`'s `CSS = """…"""` block. The web kit is a
*refinement of your TUI's own layout* (header · status band · watch rail ·
tabbed workspace · signals rail · ticker · cmd bar · footer), not a new design.
So the palette and structure drop into your tmux/Textual cockpit 1:1. Below is
what carries over cleanly, what needs a terminal-native substitute, and a
refined, paste-ready Textual theme.

---

## What carries 1:1 (truecolor terminals)

| Design token | Textual CSS | Notes |
|---|---|---|
| `--ink-900 #08080A` (app bg) | `Screen { background: #08080A; }` | identical |
| `--ink-750 #0E0E10` (chrome) | `Header / Footer / #statusband background` | identical |
| `--ink-700 #121214` (card) | panel `background` | identical |
| `--amber #D6A24A` (accent) | `.railtitle`, focus `border`, `--datatable--header` | identical |
| `--gold #D9C27E` (values) | headline `color` | identical |
| `--silver #B6B6BE` / `--dim #74747C` | body / hint `color` | identical |
| semantic mint/red/orange/teal | bias/level colors in Rich markup | identical |
| 3-column + docked bands | `#watch / #tabs / #signals`, `dock: bottom` | already your layout |
| hairline border `#26262C` | `border: solid #26262C` | identical |
| 2 Hz heartbeat | your existing `set_interval(0.5, _pulse)` | already built |
| macro ticker | your existing docked `#ticker` Static | already built |

Requires a **truecolor** terminal (`$COLORTERM=truecolor`). In tmux add:
```tmux
set -ga terminal-overrides ",*256col*:Tc"
```
On a 256-color-only terminal these soft hexes quantize to the nearest xterm
color — still readable, slightly less subtle.

## What needs a terminal-native substitute

| Web treatment | Why it can't port | Terminal-native equivalent |
|---|---|---|
| `border-radius: 6px` | cells aren't sub-divisible | use Textual's **`round`** border type (╭╮╰╯ corners) for cards; `solid`/`tall` elsewhere |
| `box-shadow` / accent **glow** | no compositing in a TTY | brighten the border to `#E6B968` **and** drive it with the existing 2 Hz pulse (swap `#26262C → #D6A24A` on live rows) |
| `letter-spacing` on labels | fixed character grid | **drop it** — carry emphasis with `text-style: bold` + amber/dim color only |
| `color-mix(... 8%, transparent)` tints | limited alpha model | Textual supports `background: #D6A24A 8%;` (percent alpha) — use that for the faint fills |
| pixel spacing scale (2–32px) | everything snaps to cells | map to **integer cells**: `2/4px→0–1`, `8px→1`, `12–16px→1–2`, `20–24px→2`, `32px→3` |
| IBM Plex Mono webfont | terminal uses the user's font | font-agnostic — the design is *all-mono*, so any terminal mono works; set Plex Mono as your terminal profile font to match exactly |
| SVG sparkline / range gauge | no vector layer | Unicode you already ship: `_spark` → `▁▂▃▄▅▆▇█`, `_range_bar` → `├──●────┤` |
| pillar fill bars | no `<div>` width | render a Rich bar: `█` × fill + `░`/`─` × rest, fill colored by health |

---

## Refined Textual theme (paste over your current `CSS`)

Same palette, tightened to the kit's hierarchy. Pure Textual CSS — no web-only
properties.

```python
CSS = """
Screen { background: #08080A; color: #CBCBD2; layers: base overlay; }

/* chrome */
Header      { background: #0E0E10; color: #D9C27E; text-style: bold; }
#statusband { height: 1; padding: 0 1; background: #0E0E10; color: #B6B6BE; }
Footer      { background: #0E0E10; color: #74747C; }

/* three-column desk */
#body    { height: 1fr; }
#watch   { width: 30; border-right: solid #26262C; padding: 1 1; }
#tabs    { width: 1fr; }
#signals { width: 36; border-left: solid #26262C; padding: 1 1; }

/* rails */
.railtitle  { color: #D6A24A; text-style: bold; }            /* no letter-spacing in a TTY */
.railsub    { color: #74747C; text-style: bold; margin-top: 1; }
#healthmini { border-top: solid #26262C; margin-top: 1; padding-top: 1; }

/* the focused-name conviction card: round border + amber left-rule */
.convictioncard { border: round #26262C; border-left: thick #D6A24A;
                  background: #0D0D10; padding: 1 2; }
.compactrow     { border: round #26262C; background: #0D0D10; padding: 1 2; margin-top: 1; }
.compactrow:hover { border: round #33333B; background: #121214; }

/* live / focused state — the glow stand-in (pair with the 2 Hz pulse) */
.live { border: round #D6A24A; }
.glow { border: round #6FA8A6; }

/* data table */
DataTable { height: 1fr; background: #08080A;
            scrollbar-size-horizontal: 1; scrollbar-size-vertical: 1;
            scrollbar-background: #0B0B0D; scrollbar-color: #26262C;
            scrollbar-color-hover: #D6A24A; }
DataTable > .datatable--cursor { background: #1C1C22; }
DataTable > .datatable--header { color: #D6A24A; text-style: bold; }

/* inputs / buttons */
Input        { border: tall #26262C; background: #0E0E10; }
Input:focus  { border: tall #D6A24A; }
Button       { background: #121214; color: #D9C27E; border: tall #26262C; height: 3; }
Button:hover { border: tall #D6A24A; }
Button.knob  { color: #B6B6BE; min-width: 9; }
Button.-run  { color: #E6B968; border: tall #D6A24A; }       /* primary ▶ Run */

/* docked bands */
#ticker { dock: bottom; height: 1; padding: 0 1; background: #0B0B0D;
          color: #B6B6BE; border-top: solid #26262C; }
#cmdbar { dock: bottom; height: 3; border: tall #26262C; background: #0B0B0D; }
#cmdbar:focus { border: tall #D6A24A; }

/* modal inspector */
InspectScreen { align: center middle; background: #08080A 70%; }
#inspect_box  { width: 72; max-width: 90%; height: auto; max-height: 80%;
                border: round #D6A24A; background: #0E0E10; padding: 1 2; }
"""
```

## Rich-markup helpers (for the cells the CSS can't draw)

```python
AMBER, GOLD, SILVER, DIM = "#D6A24A", "#D9C27E", "#B6B6BE", "#74747C"
GOOD, BAD, WARN, TEAL    = "#7FC8A0", "#D87A7A", "#CF9A5C", "#6FA8A6"

def pillar(label, score, color, width=24):
    """MACRO TAILWIND  ██████████████░░░░░░░░░░  6.7"""
    fill = round(score / 10 * width)
    bar  = f"[{color}]{'█'*fill}[/][#1B1B21]{'─'*(width-fill)}[/]"
    return f"[b {SILVER}]{label:<22}[/] {bar} [b {color}]{score:>4.1f}[/]"

def badge(text, level="info"):                # GRADE 0.74 · RISK-ON
    c = {"info":AMBER,"good":GOOD,"warn":WARN,"risk":BAD}[level]
    return f"[on #141418][{c}] {text} [/][/]"

def rating(r, band):                          #  ◆ 8.6  PRIME CONVICTION
    c = GOLD if r>=8 else AMBER if r>=6 else WARN
    return f"[b {c}]◆ {r:.1f}[/]  [b {AMBER}]{band}[/]"
```

`_spark()` and `_range_bar()` already exist in `commodityex_tui.py` — keep them;
they're exactly the kit's Sparkline and RangeBar in glyph form.

---

## Net

- **Colors, layout, ticker, heartbeat, glyphs** → already native to your TUI.
- **Radii → `round` borders, glow → bright border + pulse, fills/sparklines →
  Unicode bars** → faithful terminal stand-ins.
- **Letter-spacing & sub-cell spacing** → the only true losses; drop them and
  lean on bold + the brass/dim color hierarchy, which is what makes the look
  read anyway.

The web kit is best treated as the **high-fidelity spec**; this file is the lossy
(but very close) projection onto a character grid. Nothing here uproots a single
cockpit feature.
