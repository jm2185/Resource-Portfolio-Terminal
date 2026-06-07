"""
Trigger grammar — a tiny, SAFE expression language for pre-commitment rules (Forge M2).

This is the single most security-sensitive component in the Forge layer. Pre-commitment rules and the
swap hurdle are authored as text and stored in Living Memory — which is operator/agent-editable. That
text is **never** executed. There is NO ``eval`` / ``exec`` / ``compile`` anywhere here: an expression
is tokenized, parsed into a fixed abstract syntax tree over a CLOSED whitelist of identifiers and
functions, and walked by a hand-written evaluator. An identifier or function the whitelist doesn't
know is a parse error — so a typo, or an attempt to smuggle ``__import__`` or attribute access, simply
fails to parse. (See the Build Spec §7 hard line: "No eval/exec of memory content.")

Two fail-closed disciplines, by design:
  * **Parse-time (at SAVE):** a malformed or out-of-vocabulary expression raises ``GrammarError`` so
    M2 rejects the rule when it's written, with a clear message — bad rules never enter the record.
  * **Eval-time (at FIRE):** evaluation NEVER raises. A missing metric, an absent helper, or any
    surprise makes the offending leg ``False`` (the rule does not fire) and is noted — a Sentinel
    rule failing silent-closed can never cause a spurious trim/exit.

Supported vocabulary (every token documented; this list IS the security boundary):
  metrics      phi rho upside_pct jsf cba runway_months mri es95 price floor liq_days_90
               thesis_integrity window_open dilution_ok death_spiral prem_to_placement
               floor_headroom pctile_52w days_90
  literals     numbers (12, 0.4, -0.5), and the bare words true/false
  comparators  <  <=  >  >=  ==  !=
  helpers      no_catalyst_within_days(n)   catalyst_within_days(n)
               event:<name>                 before(event:<a>, event:<b>)
  boolean      AND  OR  NOT      grouping ( )

Pure stdlib, fully testable. The evaluation CONTEXT (metric values + trusted helper callables +
which events have occurred) is supplied by the caller (the Sentinel, M3) — the grammar reaches into
nothing on its own.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Callable, Optional

log = logging.getLogger("forge.trigger")

# ---- the closed whitelists (the security boundary) ------------------------------------------------
METRICS: frozenset = frozenset({
    "phi", "rho", "upside_pct", "jsf", "cba", "runway_months", "mri", "es95", "price", "floor",
    "liq_days_90", "days_90", "thesis_integrity", "window_open", "dilution_ok", "death_spiral",
    "prem_to_placement", "floor_headroom", "pctile_52w",
})
#: metrics that are inherently boolean (truthiness, not a numeric compare, when used bare)
BOOL_METRICS: frozenset = frozenset({"window_open", "dilution_ok", "death_spiral"})
FUNCTIONS: dict = {
    "no_catalyst_within_days": ("number",),
    "catalyst_within_days": ("number",),
    "before": ("event", "event"),
}
_COMPARATORS: frozenset = frozenset({"<", "<=", ">", ">=", "==", "!="})

# ---- tokenizer ------------------------------------------------------------------------------------
_TOKEN_RE = re.compile(r"""
    \s*(?:
      (?P<num>-?\d+(?:\.\d+)?)            # number (optionally signed)
    | (?P<op><=|>=|==|!=|<|>)             # comparator (two-char first)
    | (?P<lp>\()
    | (?P<rp>\))
    | (?P<comma>,)
    | (?P<colon>:)
    | (?P<ident>[A-Za-z_][A-Za-z0-9_]*)   # identifier / keyword
    )
""", re.VERBOSE)


class GrammarError(ValueError):
    """A trigger expression that does not parse (out-of-vocabulary token, bad syntax, wrong arity)."""


def _tokenize(expr: str) -> list:
    toks, pos, n = [], 0, len(expr)
    while pos < n:
        if expr[pos].isspace():
            pos += 1
            continue
        m = _TOKEN_RE.match(expr, pos)
        if not m or m.start() == m.end():
            raise GrammarError(f"unexpected character {expr[pos]!r} at {pos} in {expr!r}")
        pos = m.end()
        kind = m.lastgroup
        val = m.group(kind)
        toks.append((kind, val))
    toks.append(("eof", ""))
    return toks


# ---- parser (recursive descent; precedence OR < AND < NOT < comparison) ---------------------------
class _Parser:
    def __init__(self, toks: list):
        self.toks = toks
        self.i = 0
        self.depth = 0                                  # bound recursion (defensive)

    def _peek(self):
        return self.toks[self.i]

    def _next(self):
        t = self.toks[self.i]
        self.i += 1
        return t

    def _expect(self, kind):
        t = self._next()
        if t[0] != kind:
            raise GrammarError(f"expected {kind}, got {t[1]!r}")
        return t

    def parse(self):
        node = self._or()
        if self._peek()[0] != "eof":
            raise GrammarError(f"trailing input near {self._peek()[1]!r}")
        return node

    def _or(self):
        node = self._and()
        while self._is_kw("OR"):
            self._next()
            node = ("or", node, self._and())
        return node

    def _and(self):
        node = self._not()
        while self._is_kw("AND"):
            self._next()
            node = ("and", node, self._not())
        return node

    def _not(self):
        if self._is_kw("NOT"):
            self._next()
            self.depth += 1
            if self.depth > 64:
                raise GrammarError("expression too deeply nested")
            return ("not", self._not())
        return self._comparison()

    def _comparison(self):
        left = self._primary()
        t = self._peek()
        if t[0] == "op":
            self._next()
            right = self._primary()
            return ("cmp", t[1], left, right)
        return left                                     # bare boolean primary

    def _primary(self):
        t = self._peek()
        if t[0] == "lp":
            self._next()
            self.depth += 1
            if self.depth > 64:
                raise GrammarError("expression too deeply nested")
            node = self._or()
            self._expect("rp")
            self.depth -= 1
            return node
        if t[0] == "num":
            self._next()
            return ("num", float(t[1]))
        if t[0] == "ident":
            return self._ident()
        raise GrammarError(f"unexpected token {t[1]!r}")

    def _ident(self):
        name = self._next()[1]
        low = name.lower()
        # keywords AND/OR/NOT shouldn't reach here as a primary
        if low in ("and", "or", "not"):
            raise GrammarError(f"misplaced keyword {name!r}")
        if low in ("true", "false"):
            return ("num", 1.0 if low == "true" else 0.0)
        # event:<name>
        if low == "event":
            self._expect("colon")
            ev = self._expect("ident")[1]
            return ("event", ev)
        # function call?
        if self._peek()[0] == "lp":
            if low not in FUNCTIONS:
                raise GrammarError(f"unknown function {name!r}")
            return self._call(low)
        # bare metric
        if low not in METRICS:
            raise GrammarError(f"unknown identifier {name!r} (not a known metric)")
        return ("metric", low)

    def _call(self, name):
        self._expect("lp")
        sig = FUNCTIONS[name]
        args = []
        if self._peek()[0] != "rp":
            args.append(self._arg(sig[len(args)] if len(args) < len(sig) else None))
            while self._peek()[0] == "comma":
                self._next()
                expected = sig[len(args)] if len(args) < len(sig) else None
                args.append(self._arg(expected))
        self._expect("rp")
        if len(args) != len(sig):
            raise GrammarError(f"{name} expects {len(sig)} arg(s), got {len(args)}")
        return ("call", name, args)

    def _arg(self, expected):
        t = self._peek()
        if expected == "number":
            if t[0] != "num":
                raise GrammarError(f"expected a number argument, got {t[1]!r}")
            self._next()
            return ("num", float(t[1]))
        if expected == "event":
            if not (t[0] == "ident" and t[1].lower() == "event"):
                raise GrammarError(f"expected event:<name>, got {t[1]!r}")
            return self._ident()
        raise GrammarError(f"unexpected argument {t[1]!r}")

    def _is_kw(self, kw):
        t = self._peek()
        return t[0] == "ident" and t[1].upper() == kw


def parse(expr: str):
    """Parse a trigger string into an AST, raising ``GrammarError`` on anything out-of-vocabulary or
    malformed. Use at SAVE time so bad rules are rejected before they enter the record."""
    if not isinstance(expr, str) or not expr.strip():
        raise GrammarError("empty trigger expression")
    return _Parser(_tokenize(expr)).parse()


def metrics_referenced(expr: str) -> set:
    """The set of metric names a (valid) expression reads — lets M3 know what context to populate.
    Returns an empty set if the expression doesn't parse (caller should validate separately)."""
    try:
        ast = parse(expr)
    except GrammarError:
        return set()
    out: set = set()

    def walk(n):
        if not isinstance(n, tuple):
            return
        if n[0] == "metric":
            out.add(n[1])
        for child in n[1:]:
            if isinstance(child, tuple):
                walk(child)
            elif isinstance(child, list):
                for c in child:
                    walk(c)
    walk(ast)
    return out


# ---- evaluator (NEVER raises; missing data -> fail closed to False) -------------------------------
_MISSING = object()


def _num(x):
    try:
        f = float(x)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


class _Evaluator:
    def __init__(self, ctx: dict):
        self.ctx = ctx or {}
        self.notes: list = []

    def eval(self, node) -> bool:
        return bool(self._truth(node))

    def _truth(self, node):
        try:
            op = node[0]
        except (TypeError, IndexError):
            return False
        if op == "or":
            return self._truth(node[1]) or self._truth(node[2])
        if op == "and":
            return self._truth(node[1]) and self._truth(node[2])
        if op == "not":
            return not self._truth(node[1])
        if op == "cmp":
            return self._cmp(node[1], node[2], node[3])
        # a bare primary used as a boolean
        v = self._value(node)
        return bool(v) if v is not None else False

    def _cmp(self, opsym, lnode, rnode):
        lv, rv = self._value(lnode), self._value(rnode)
        if lv is None or rv is None:
            self.notes.append(f"comparison skipped (missing value): {opsym}")
            return False                               # fail closed
        ln, rn = _num(lv), _num(rv)
        if ln is None or rn is None:
            return False
        return {"<": ln < rn, "<=": ln <= rn, ">": ln > rn, ">=": ln >= rn,
                "==": ln == rn, "!=": ln != rn}[opsym]

    def _value(self, node):
        """Resolve a primary to a scalar (number / bool→1.0/0.0) or None if unknown."""
        op = node[0]
        if op == "num":
            return node[1]
        if op == "metric":
            val = self.ctx.get(node[1], _MISSING)
            if val is _MISSING or val is None:
                self.notes.append(f"missing metric: {node[1]}")
                return None
            if isinstance(val, bool):
                return 1.0 if val else 0.0
            return val
        if op == "event":
            events = self.ctx.get("events") or {}
            return 1.0 if node[1] in events else 0.0
        if op == "call":
            return self._call(node[1], node[2])
        # a boolean sub-expression used where a value is expected
        if op in ("and", "or", "not", "cmp"):
            return 1.0 if self._truth(node) else 0.0
        return None

    def _call(self, name, args):
        if name in ("no_catalyst_within_days", "catalyst_within_days"):
            fn = self.ctx.get("catalyst_within_days")
            n = self._value(args[0])
            if not callable(fn) or n is None:
                self.notes.append(f"helper unavailable: {name}")
                return None
            try:
                within = bool(fn(int(n)))
            except Exception:                          # trusted callable, but never let it crash eval
                return None
            return 1.0 if (within if name == "catalyst_within_days" else not within) else 0.0
        if name == "before":
            events = self.ctx.get("events") or {}
            a, b = args[0][1], args[1][1]
            ta, tb = events.get(a), events.get(b)
            if ta is None or tb is None:
                return 0.0                             # an event that hasn't occurred can't be "before"
            try:
                return 1.0 if ta < tb else 0.0
            except TypeError:
                return None
        return None


def evaluate(expr_or_ast, ctx: dict) -> bool:
    """Evaluate a trigger against a context dict, returning a plain bool. NEVER raises — a parse
    failure or any missing datum yields ``False`` (fail closed) and logs a warning. Use ``safe_eval``
    when you also want the diagnostic notes."""
    return safe_eval(expr_or_ast, ctx)[0]


def safe_eval(expr_or_ast, ctx: dict) -> tuple:
    """Like ``evaluate`` but returns ``(fired: bool, notes: list[str])`` — the notes explain any leg
    that failed closed (missing metric, unavailable helper). Used by the Sentinel for its alert copy."""
    try:
        ast = parse(expr_or_ast) if isinstance(expr_or_ast, str) else expr_or_ast
    except GrammarError as e:
        log.warning("trigger failed to parse (fail-closed to False): %s", e)
        return False, [f"parse error: {e}"]
    ev = _Evaluator(ctx)
    try:
        fired = ev.eval(ast)
    except Exception as e:                              # defensive: evaluation must never crash a sweep
        log.warning("trigger evaluation error (fail-closed to False): %s", e)
        return False, [f"eval error: {e}"]
    return fired, ev.notes
