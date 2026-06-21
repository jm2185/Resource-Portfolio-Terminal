"""Pure helpers for the Agent-Hub Quest-Log feed — deliberately free of textual/rich so they are
unit-testable without the TUI stack. Imported by commodityex_tui.py.

The feed's job: while a run is LIVE, stream its agent feed (expanded); once the result is in, settle
to a single collapsed RESULT line — the conclusion, not the "I will…" step narration. These two
helpers encode exactly that: `is_run_expanded` (default fold state by run status) and `reply_gist`
(signal extraction for the collapsed line)."""
import json
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


# A line that starts the actionable RESULT (a labelled section / conclusion), used to find where the
# 'I will…' process narration ends and the answer begins.
_RESULT_ANCHOR = re.compile(
    r"^\s*#{0,6}\s*\*{0,2}\s*(summary of actions|summary|key decisions?|recommendations?|verdict|"
    r"findings?|shortlist|top picks?|bottom line|conclusion|the call|net:|results?\b|outcome|"
    r"here(?:'s| is| are)\b|i recommend|my recommendation)\b", re.I)
# A leading line that is pure process narration ("I will search…", "I have completed…").
_NARRATION = re.compile(
    r"^\s*(?:[-*•]\s*)?\*{0,2}\s*(i will\b|i'll\b|i am going\b|i'm going\b|let me\b|next,|first,|"
    r"then,|now i\b|i need to\b|i started\b|i have (?:now )?(?:completed|finished|run|ran|read|"
    r"viewed|searched|listed|edited|created|inspected|examined|updated|modified)\b)", re.I)


def condense_reply(text, min_narration=4):
    """A finished agent reply often opens with a long block of 'I will…' process narration — useful to
    watch live, noise once the run is done — before the actionable result. When that pattern is present,
    return just the result: the first labelled section (Summary / Key Decisions / Recommendation / …),
    or failing that everything after the narration block. CONSERVATIVE — only condenses when the leading
    narration block is real (≥ ``min_narration`` lines); otherwise returns the text unchanged, so a
    normal answer is never trimmed. (``shown != text`` ⇔ it condensed.)"""
    t = str(text or "")
    lines = t.split("\n")
    # the first labelled result section (the narration ends and the answer begins here), if any
    anchor = next((i for i, ln in enumerate(lines)
                   if ln.strip() and _RESULT_ANCHOR.match(ln.strip())), None)
    region_end = anchor if anchor is not None else len(lines)
    # walk the leading region: count narration lines and find where the narration block ends. A short
    # stray preamble before the block is tolerated (real replies open with a fragment, then 'I will…').
    narr = block_end = 0
    seen = False
    for i in range(region_end):
        s = lines[i].strip()
        if not s:                                     # blank line — still inside the block
            block_end = i + 1
        elif _NARRATION.match(s):
            narr += 1; seen = True; block_end = i + 1
        elif not seen and i < 2:                      # a stray preamble line before narration starts
            block_end = i + 1
        else:
            break                                     # first real content line ends the block
    if narr < min_narration:
        return t                                      # not a process-log dump — leave it alone
    cut = anchor if anchor is not None else block_end
    return "\n".join(lines[cut:]).strip() or t


def ask_failure_message(kind, *, timeout_s=None, partial="", exc=None):
    """Compose the thread reply for a background ask that ended WITHOUT a clean result, so the chat
    shows WHY instead of hanging on 'thinking…'. ``kind`` ∈ {'timeout', 'cli_missing', 'error'}.
    On a timeout any streamed ``partial`` output is preserved above the notice (don't discard work)."""
    partial = (partial or "").strip()
    if kind == "timeout":
        tail = (f"⚠ ask timed out after {timeout_s}s — raise CEX_ASK_TIMEOUT or narrow the task."
                if timeout_s is not None
                else "⚠ ask timed out — raise CEX_ASK_TIMEOUT or narrow the task.")
        return f"{partial}\n\n{tail} (partial output above)" if partial else tail + " No output was produced."
    if kind == "cli_missing":
        return "⚠ ask CLI not found — set CEX_ASK_CMD to your `claude` / agent command."
    return f"⚠ ask failed: {exc}" if exc is not None else "⚠ ask failed (unknown error)."


def ask_timeout_seconds(override=None, default=900):
    """Ceiling (seconds) for a main-chat ask (`_ask_agent_bg`) — the orchestrator OR a named research
    seat. Both do real web work and `claude -p` only prints on completion, so the ceiling must clear
    MINUTES, not 300s; a quick question still returns fast (the ceiling only bites long work, so making
    it generous costs nothing). The quick Concierge dock is a separate, shorter lane. An explicit
    override (CEX_ASK_TIMEOUT) always wins."""
    if override:
        try:
            return int(override)
        except (TypeError, ValueError):
            pass
    return default


# ---- streaming (CEX_ASK_STREAM): parse Claude Code stream-json so the tape updates live ---------- #

def stream_json_event_text(event):
    """For one Claude Code stream-json event (a dict, one per output line), return
    ``(assistant_text, result_text)``:
      • assistant_text — any text emitted in an 'assistant' turn (for the LIVE tape), else ''.
      • result_text   — the final answer if this is the terminal 'result' event, else None.
    Other / unknown events return ('', None)."""
    if not isinstance(event, dict):
        return "", None
    t = event.get("type")
    if t == "assistant":
        content = (event.get("message") or {}).get("content")
        if isinstance(content, list):
            txt = "\n".join(b.get("text", "") for b in content
                            if isinstance(b, dict) and b.get("type") == "text")
            return txt.strip(), None
        return str(content or "").strip(), None
    if t == "result":
        r = event.get("result")
        if r is None:
            r = (event.get("message") or {}).get("content")
        return "", ("" if r is None else str(r))
    return "", None


def reduce_stream_json(lines, on_update=None):
    """Fold Claude Code stream-json (one JSON event per line) into the final reply, emitting the
    accumulated assistant text via ``on_update(text, n)`` as turns land — that's the live tape, the
    whole point of streaming. Returns the terminal 'result' text if present, else the accumulated
    assistant text, else the raw lines joined (a fallback so a non-JSON stream never yields a blank
    reply). Pure — feed it any iterable of line strings (a real pipe via readline, or a list in tests)."""
    pieces, raw, result, n = [], [], None, 0
    for line in lines:
        s = str(line).rstrip("\r\n")
        if not s.strip():
            continue
        try:
            ev = json.loads(s)
        except Exception:
            raw.append(s)                                  # not JSON — keep as a plain-text fallback
            continue
        atext, rtext = stream_json_event_text(ev)
        if atext:
            pieces.append(atext)
            n += 1
            if on_update:
                on_update("\n".join(pieces), n)
        if rtext is not None:
            result = rtext
    if result and result.strip():
        return result.strip()
    if pieces:
        return "\n".join(pieces).strip()
    return "\n".join(raw).strip()


def is_run_expanded(it, expanded):
    """Default fold state for a Quest-Log row: a LIVE run streams its feed (expanded); a finished run
    settles to a collapsed result line (the user can click to re-open it). A user toggle — recorded in
    ``expanded`` (a set of uids) — is always honoured, so manual expand/collapse still wins."""
    return (it.get("status") == "running") or (it.get("uid") in (expanded or ()))
