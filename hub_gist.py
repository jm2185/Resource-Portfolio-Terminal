"""Pure helpers for the Agent-Hub Quest-Log feed — deliberately free of textual/rich so they are
unit-testable without the TUI stack. Imported by commodityex_tui.py.

The feed's job: while a run is LIVE, stream its agent feed (expanded); once the result is in, settle
to a single collapsed RESULT line — the conclusion, not the "I will…" step narration. These two
helpers encode exactly that: `is_run_expanded` (default fold state by run status) and `reply_gist`
(signal extraction for the collapsed line)."""
import re

# Labelled conclusion sections we prefer to surface (this desk's vocabulary: "the call", "Net:" …).
_GIST_LABELS = ("key decision", "summary", "verdict", "recommendation", "top pick", "bottom line",
                "tl;dr", "conclusion", "the call", "net:", "result")
# Leading step-narration we skip when no labelled section exists ("I will search the web…").
_GIST_NARRATION = ("i will", "i'll", "i am going", "i'm going", "i have ", "i need to", "let me ",
                   "first,", "next,", "then,", "now i", "i started", "i'll start")


def _clip(s, n):
    """Truncate with an ellipsis so a cut line still reads as 'there's more'."""
    s = str(s)
    return s if len(s) <= n else s[:n].rstrip() + "…"


def reply_gist(text, width=120):
    """Pull the SIGNAL out of a verbose agent reply for the collapsed feed line. Prefer the content
    under a labelled tail section (Summary / Key Decisions / Verdict / Recommendation / Top pick),
    else the first line that isn't pure 'I will…' step narration; markdown chrome stripped. Returns
    '' for empty input."""
    lines = []
    for ln in str(text or "").replace("\r", "").split("\n"):
        ln = re.sub(r"^\s*#{1,6}\s*", "", ln)                  # unwrap "### Heading"
        ln = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s+", "", ln)       # unwrap "- " / "* " / "1. " bullets
        ln = ln.replace("**", "").replace("`", "").strip(" *_—-·")
        if ln and not set(ln) <= {":", ".", "—", "-", "=", " "}:
            lines.append(ln)
    if not lines:
        return ""

    def _is_header(s):                                          # a label whose content is the NEXT line
        return s.endswith(":") or len(s) <= 30

    # 1) a labelled conclusion section — surface its content (header + first content line, or the line)
    for i, ln in enumerate(lines):
        low = ln.lower()
        if any(low.startswith(lbl) for lbl in _GIST_LABELS):
            if _is_header(ln):
                nxt = next((x for x in lines[i + 1:] if x), "")
                if nxt:
                    return _clip(" ".join((ln.rstrip(":") + " — " + nxt).split()), width)
            return _clip(" ".join(ln.split()), width)
    # 2) else the first line that isn't step-narration
    for ln in lines:
        if not ln.lower().startswith(_GIST_NARRATION):
            return _clip(" ".join(ln.split()), width)
    # 3) all narration (rare for a final message) — the first line, clipped
    return _clip(" ".join(lines[0].split()), width)


def is_run_expanded(it, expanded):
    """Default fold state for a Quest-Log row: a LIVE run streams its feed (expanded); a finished run
    settles to a collapsed result line (the user can click to re-open it). A user toggle — recorded in
    ``expanded`` (a set of uids) — is always honoured, so manual expand/collapse still wins."""
    return (it.get("status") == "running") or (it.get("uid") in (expanded or ()))
