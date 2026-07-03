"""The PIPELINE canvas must label each node with the run's ACTUAL seat, not the registry's
aspiration (2026-07-03 operator report: the working lane truthfully read `claude ◇sonnet MANUAL`
for a gauntlet run while the canvas's SCOUT node still advertised ◇gemini-flash — the registry
default). The canvas now consumes states[(si, agent, "model"/"provider")], resolved exactly like
the working lane (live record first, else the effective provider incl. the agy→Claude fallback).

Also pins the `u` command-manual overlay's data: every glossary group is non-empty and the core
verbs the operator relies on are present.
"""
import unittest

from rich.console import Console

import commodityex_tui as t
from cockpit_widgets import COMMAND_GLOSSARY, _blend_chain_canvas, _blend_node_card


def _render(obj) -> str:
    con = Console(record=True, width=200)
    con.print(obj)
    return con.export_text()


class CanvasModelTruth(unittest.TestCase):
    def test_node_card_prefers_the_live_model_over_the_registry(self):
        # scout's registry seat is gemini/gemini-flash; a run that actually executes on the
        # Claude seat (agy fallback) must read ◇sonnet on the canvas, like the working lane.
        card = _blend_node_card("scout", "running", model="sonnet", provider="claude")
        text = "\n".join(seg.plain if hasattr(seg, "plain") else str(seg) for seg in card)
        self.assertIn("◇sonnet", text)
        self.assertNotIn("gemini-flash", text)

    def test_node_card_falls_back_to_the_registry_when_no_live_seat(self):
        card = _blend_node_card("scout", "queued")
        text = "\n".join(seg.plain if hasattr(seg, "plain") else str(seg) for seg in card)
        self.assertIn("◇gemini-flash", text)

    def test_canvas_threads_state_model_overrides_into_the_cards(self):
        stages = [{"agents": ["scout"], "note": "find"},
                  {"agents": ["synthesis"], "note": "rank"}]
        states = {(0, "scout"): "running", (0, "scout", "model"): "sonnet",
                  (0, "scout", "provider"): "claude", (1, "synthesis"): "queued"}
        text = _render(_blend_chain_canvas(stages, states, target="HG.CN", target_role=""))
        self.assertIn("◇sonnet", text)           # the live scout seat, not the registry
        self.assertNotIn("gemini-flash", text)   # no stage advertises the aspiration
        self.assertIn("◇opus", text)             # synthesis queued → registry (claude/opus) is honest

    def test_chain_annotation_resolves_like_the_working_lane(self):
        # the same resolution _chain() stamps on every node: a running agent takes its inflight
        # record's provider; anything else the effective (agy-fallback-aware) provider. On a box
        # without the Gemini CLI, BOTH paths land the scout on the Claude seat — ◇sonnet.
        from cockpit_widgets import _run_model_label
        app = t.Cockpit()
        live_provider = "claude"                        # what the gauntlet run actually recorded
        self.assertEqual(_run_model_label("scout", live_provider), "sonnet")
        if not app._has_gemini():                       # effective resolution for queued stages
            self.assertEqual(_run_model_label("scout", app._agent_provider("scout")), "sonnet")
        # and the surface method that does the stamping exists on the pipeline canvas
        import cockpit_surfaces as cs
        self.assertTrue(callable(getattr(cs.PipelineSurface, "_chain", None)))
        self.assertTrue(callable(getattr(cs.PipelineSurface, "_chain_states", None)))


class CommandManual(unittest.TestCase):
    def test_every_group_is_non_empty(self):
        self.assertGreaterEqual(len(COMMAND_GLOSSARY), 5)
        for group, rows in COMMAND_GLOSSARY:
            self.assertTrue(group.strip())
            self.assertTrue(rows, f"empty glossary group: {group}")
            for cmd, use in rows:
                self.assertTrue(cmd.strip() and use.strip())

    def test_core_verbs_present(self):
        flat = " ".join(cmd for _g, rows in COMMAND_GLOSSARY for cmd, _u in rows)
        for verb in ("/council", "/whatif", "/screen", "/gauntlet", "/rotate", "/confirm",
                     "/pipeline", "backfill_price_history"):
            self.assertIn(verb, flat)

    def test_binding_and_action_exist(self):
        keys = [(b[0] if isinstance(b, tuple) else b.key) for b in t.Cockpit.BINDINGS]
        self.assertIn("u", keys)
        self.assertTrue(callable(getattr(t.Cockpit, "action_cmd_glossary", None)))


if __name__ == "__main__":
    unittest.main()
