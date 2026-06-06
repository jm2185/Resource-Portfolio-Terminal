"""
cockpit_scheduler.py — recurring agent work for the CommodityEx cockpit (the autonomy spine).

Pure scheduling logic + a small JSON-persisted job store. The dashboard ticks it; this module decides
which jobs are DUE and — gated by the autonomy dial — whether each should RUN (auto), be PROPOSED
(propose), or be SKIPPED (manual). The point is agents that don't just *research* but keep improving
the terminal: scout new names, backtest / calibrate the book, verify data, brainstorm, and draft new
agents — always emitting a **review artifact**, never auto-committing.

Two hard invariants live here so they can't be bypassed:
  1. **The dial is the boundary.** ``decide(autonomy)`` is the only thing that turns "due" into action.
     Default ``propose`` means nothing runs unattended without a human ✓.
  2. **Jobs produce drafts, not commits.** The prompts ask for review artifacts; the cockpit's runner
     writes them to ``data/agent_drafts/`` + Living Memory. Committing / pushing / applying stays a
     human action (the cockpit never does it).

Pure stdlib, fully testable. Persistence is a flat JSON list at ``data/cockpit_jobs.json``.
"""
from __future__ import annotations

import json
import os
import time
import uuid

# kind -> (label, default cadence minutes, prompt template). Prompts are improvement-oriented and
# self-limiting — they ask for a REVIEW ARTIFACT (note / shortlist / report / draft), never a commit.
JOB_KINDS = {
    "research": ("Research", 720,
                 "Research {topic} for the silver / junior-mining book and write a concise, "
                 "straight-to-source note (issuer PR / SEDAR+ / EDGAR). Flag what's actionable."),
    "scout": ("Scout", 1440,
              "Scout for overlooked {topic} that fit a Druckenmiller-style asymmetric silver / junior "
              "book (margin of safety, convex upside, regime fit). Return a ranked shortlist with why."),
    "backtest": ("Backtest", 1440,
                 "Backtest / calibrate the book's closed decisions ({topic}). Report the expectancy "
                 "scorecard (slugging · expectancy · upside-capture · downside-containment) and any "
                 "tunable the evidence supports — as a PROPOSAL routed through /confirm, do not apply it."),
    "verify": ("Verify data", 720,
               "Verify {topic}: sweep catalysts straight-to-source and check ticker / company / "
               "archetype / alias integrity. Flag anything stale, misattributed, or mis-ID'd."),
    "brainstorm": ("Brainstorm", 2880,
                   "Brainstorm concrete improvements to {topic} for the CommodityEx cockpit, ranked by "
                   "payoff vs effort. Ideas only — no code changes."),
    "build": ("Draft / build", 4320,
              "Draft an implementation for {topic}: a new agent spec, or a small terminal improvement. "
              "Produce a REVIEW DRAFT — a markdown spec plus the proposed change as a fenced patch. "
              "Do NOT edit tracked files, commit, or push; this is for human review."),
}
DEFAULT_KIND = "research"


def _now(now=None) -> float:
    return float(now) if now is not None else time.time()


def new_job(kind: str, topic: str = "", label: str = "", every_min=None, now=None) -> dict:
    """Build a job. First run is scheduled one cadence out (not immediately) — use run-now for that."""
    k = kind if kind in JOB_KINDS else DEFAULT_KIND
    lbl, cadence, _ = JOB_KINDS[k]
    every = max(1, int(every_min or cadence))
    topic = (topic or "").strip()
    t = _now(now)
    return {"id": uuid.uuid4().hex[:8], "kind": k, "topic": topic,
            "label": (label.strip() or (f"{lbl}: {topic}" if topic else lbl))[:48],
            "every_min": every, "enabled": True, "created": t,
            "last_run": None, "runs": 0, "next_due": t + every * 60}


def prompt_for(job: dict) -> str:
    tmpl = JOB_KINDS.get(job.get("kind"), JOB_KINDS[DEFAULT_KIND])[2]
    return tmpl.format(topic=(job.get("topic") or "the book"))


def due_jobs(jobs, now=None) -> list:
    t = _now(now)
    return [j for j in jobs if j.get("enabled") and (j.get("next_due") or 0) <= t]


def decide(autonomy: str) -> str:
    """The autonomy dial → what a DUE job does. This is the only place 'due' becomes action."""
    return {"manual": "skip", "propose": "propose", "auto": "run"}.get(autonomy, "propose")


def mark_ran(job: dict, now=None) -> dict:
    t = _now(now)
    job["last_run"] = t
    job["runs"] = int(job.get("runs", 0)) + 1
    job["next_due"] = t + max(1, int(job.get("every_min", 1440))) * 60
    return job


def snooze(job: dict, minutes, now=None) -> dict:
    job["next_due"] = _now(now) + max(1, int(minutes)) * 60
    return job


def load_jobs(path: str) -> list:
    try:
        with open(path, encoding="utf-8") as fh:
            return [j for j in ((json.load(fh) or {}).get("jobs") or []) if isinstance(j, dict)]
    except Exception:
        return []


def save_jobs(path: str, jobs) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"jobs": list(jobs)}, fh, indent=2)
    os.replace(tmp, path)
