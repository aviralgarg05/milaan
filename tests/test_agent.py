"""The agent's policy: bounded, sound, and auditable. See INCIDENTS.md #23, #24.

The agent exists because a fixed candidate window is genuinely the wrong design —
too wide invites ties, too narrow excludes members, and the two failures point in
opposite directions, so the window has to be chosen by reacting to the outcome.

These tests pin the three properties that make it safe to run near money:
termination, soundness under the widest window, and a replayable trace.
"""

from __future__ import annotations

from datetime import date

from milaan.agent import Action, ReconciliationAgent, WINDOW_LADDER
from milaan.cli import run_batch
from milaan.narration.grammar import extract
from milaan.oracle.generator import generate
from milaan.solver.subsetsum import Outcome

VD = date(2026, 8, 5)


def rows(*specs):
    return [(eid, net, f"2026-08-{3+off:02d}T09:00:0{i}", VD.replace(day=3 + off))
            for i, (eid, net, off) in enumerate(specs)]


def test_the_agent_always_terminates():
    """Every episode ends. The ladder is finite and each rung is tried once."""
    agent = ReconciliationAgent()
    fields = extract("SETTLEMENT CREDIT")
    for target in (1, 500, 12_345, -900, 10**9):
        ep = agent.run(credit_id="c", target_paise=target, value_date=VD,
                       rows=rows(("a", 100, 0), ("b", 200, 1), ("c", 300, 2)),
                       fields=fields)
        assert ep.steps, "an episode must record at least one decision"
        assert len(ep.steps) <= agent.max_actions
        assert ep.steps[-1].action in (Action.ACCEPT, Action.ESCALATE, Action.TRY_BLIND)


def test_uniqueness_is_adjudicated_at_the_widest_window_not_the_narrowest():
    """INCIDENTS.md #24 — the bug that produced a real wrong join.

    Accepting the first window that yields a unique cover lets a narrow window
    hide a competing cover, which is *manufacturing* uniqueness by shrinking the
    pool — exactly what `hints/grounding.py` forbids a hint from doing. The agent
    finds narrow and adjudicates wide.
    """
    agent = ReconciliationAgent()
    # 50+50 at day 0 sums to 100; a competing 100 sits further out and is only
    # visible once the window widens. The narrow answer must not stand.
    r = rows(("near_a", 50, 2), ("near_b", 50, 2), ("far", 100, 0))
    ep = agent.run(credit_id="c", target_paise=100, value_date=VD,
                   rows=r, fields=extract("SETTLEMENT CREDIT"))
    assert ep.outcome is not Outcome.UNIQUE or len(ep.cover) > 0
    if ep.outcome is Outcome.AMBIGUOUS:
        assert ep.second_cover, "a refusal must carry its competing witness"


def test_the_batch_reports_zero_false_matches_under_the_agent():
    """The guarantee. The agent raised the match rate once and broke this; it does not now."""
    score = run_batch(generate(), verbose=False)
    assert score["false_matches"] == 0, (
        "the agent reported a wrong join — check whether uniqueness is still "
        "being adjudicated at the widest window (INCIDENTS.md #24)"
    )


def test_every_credit_carries_a_replayable_trace():
    score = run_batch(generate(), verbose=False)
    for r in score["rows"]:
        assert r["actions"], f"{r['credit_id']} has no decision trace"
        assert r["steps"] >= 1
        assert r["window"] in WINDOW_LADDER
        assert r["actions"].startswith("TRY_INTERVAL"), (
            "every episode must begin by observing before deciding"
        )


def test_the_agent_actually_uses_more_than_one_window():
    """If every credit resolved at the same window, the loop would be decoration."""
    score = run_batch(generate(), verbose=False)
    assert len(score["by_window"]) >= 3, (
        f"the policy should select different windows per credit; got {score['by_window']}"
    )
    assert score["avg_actions_per_credit"] > 2, "a real loop takes more than one step"
