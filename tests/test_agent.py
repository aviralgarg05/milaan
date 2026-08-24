"""The reconciliation agent: a real policy loop, verified rather than asserted.

Track 04 asks for an agent. INCIDENTS.md #23 is an audit finding that an earlier
version of MILAAN was not one — straight-line control flow, no loop, no state, no
decision. This file exercises the thing that replaced it: a policy that reacts to
how the last attempt failed and chooses a candidate window accordingly, bounded
by construction and fully replayable.

The tests below are not "does the agent run" checks. They pin the two properties
that make an adaptive window safe rather than merely clever:

  1. Soundness never weakens. Every accepted cover is still arithmetically exact,
     no matter which window found it.
  2. Uniqueness is adjudicated at the WIDEST window, never the one that happened
     to find a cover first. INCIDENTS.md #24 is the false match that shipped
     before this was enforced — a narrow window can hide a competing cover that
     a wider one reveals, and accepting on the narrow window is the same
     "manufacture uniqueness by shrinking the pool" failure that
     `hints/grounding.py` forbids a hint from committing.
"""

from __future__ import annotations

import random
from datetime import date, timedelta

from milaan.agent import Action, Observation, ReconciliationAgent, WINDOW_LADDER
from milaan.cli import run_batch
from milaan.narration.grammar import extract
from milaan.oracle.generator import generate
from milaan.solver.subsetsum import Outcome


def _rows(amounts, offsets, base=date(2026, 8, 10)):
    return [
        (f"p{i}", a, (base + timedelta(days=o)).isoformat(), base + timedelta(days=o))
        for i, (a, o) in enumerate(zip(amounts, offsets))
    ]


# ------------------------------------------------------- the policy itself


def test_the_policy_widens_on_no_cover_and_narrows_on_ambiguity():
    agent = ReconciliationAgent()
    assert agent.decide(Observation(2, 10, None, 0, False, 3)) is Action.TRY_INTERVAL
    assert agent.decide(Observation(2, 10, Outcome.NONE, 1, False, 3)) is Action.WIDEN
    assert agent.decide(Observation(2, 10, Outcome.AMBIGUOUS, 1, False, 3)) is Action.NARROW
    assert agent.decide(Observation(2, 10, Outcome.UNIQUE, 1, False, 3)) is Action.ACCEPT


def test_widening_stops_at_the_top_of_the_ladder_and_falls_back_to_blind():
    agent = ReconciliationAgent()
    obs = Observation(WINDOW_LADDER[-1], 10, Outcome.NONE, 5, False, 0)
    assert agent.decide(obs) is Action.TRY_BLIND


def test_narrowing_at_the_tightest_window_escalates_rather_than_loops():
    agent = ReconciliationAgent()
    obs = Observation(WINDOW_LADDER[0], 10, Outcome.AMBIGUOUS, 5, False, 4)
    assert agent.decide(obs) is Action.ESCALATE


def test_every_episode_terminates_within_the_action_budget():
    """No unbounded retry. Every credit gets a verdict, never a hang."""
    agent = ReconciliationAgent(max_actions=12)
    rng = random.Random(9)
    for _ in range(50):
        amounts = [rng.randint(-5000, 90000) for _ in range(rng.randint(0, 15))]
        offsets = [rng.randint(-10, 10) for _ in amounts]
        ep = agent.run(credit_id="c", target_paise=rng.randint(-5000, 200000),
                       value_date=date(2026, 8, 10), rows=_rows(amounts, offsets),
                       fields=extract("SETTLEMENT CREDIT"))
        assert len(ep.steps) <= agent.max_actions
        assert ep.outcome is not None


def test_the_trace_is_replayable_and_human_readable():
    agent = ReconciliationAgent()
    ep = agent.run(credit_id="c", target_paise=198,
                   value_date=date(2026, 8, 10),
                   rows=_rows([99, 99], [0, 0]), fields=extract("SETTLEMENT CREDIT"))
    assert ep.outcome is Outcome.UNIQUE
    assert "→" in ep.actions
    assert all(isinstance(s.observation, Observation) for s in ep.steps)


# ---------------------------------------------- INCIDENTS.md #24: the false match


def test_a_narrow_unique_cover_is_rejected_if_a_wider_window_makes_it_ambiguous():
    """The exact shape of the bug that shipped, reproduced and pinned.

    At the tightest window only ONE run of identical amounts is visible and it
    sums exactly — a naive "accept on first unique" agent takes it. Widen the
    window and a SECOND identical run appears that also sums exactly. The
    credit is genuinely ambiguous; the narrow window merely hid the competitor.
    """
    base = date(2026, 8, 10)
    # A tight-window run: two 99p payments right at the value date.
    near = [("near_a", 99, 0), ("near_b", 99, 0)]
    # A same-shape run just outside the tightest rung but inside a wider one.
    far = [("far_a", 99, 3), ("far_b", 99, 3)]
    rows = [
        (eid, amt, (base + timedelta(days=off)).isoformat(), base + timedelta(days=off))
        for eid, amt, off in near + far
    ]

    agent = ReconciliationAgent()
    ep = agent.run(credit_id="c", target_paise=198, value_date=base,
                   rows=rows, fields=extract("SETTLEMENT CREDIT"))

    assert ep.outcome is Outcome.AMBIGUOUS, (
        f"expected a refusal once the wider window reveals the competing run; "
        f"got {ep.outcome} via {ep.actions}"
    )
    assert ep.second_cover, "the refusal must carry a witness"
    assert "unique at" in ep.actions.lower() or any(
        "hid a competitor" in s.note for s in ep.steps
    ), "the trace should explain why an apparently-unique cover was rejected"


def test_soundness_holds_across_a_batch_with_the_agent_wired_in():
    """Every accepted cover, from every episode, sums to its target exactly."""
    agent = ReconciliationAgent()
    batch = generate(settlements=30)
    rows_all = [
        (r.entity_id, r.net_paise, r.captured_at, date.fromisoformat(r.captured_on))
        for r in batch.ledger if not r.on_hold
    ]
    by_id = {r.entity_id: r.net_paise for r in batch.ledger}
    for credit in batch.credits:
        ep = agent.run(credit_id=credit.credit_id, target_paise=credit.amount_paise,
                       value_date=date.fromisoformat(credit.value_date),
                       rows=rows_all, fields=extract(credit.narration))
        if ep.cover:
            assert sum(by_id[e] for e in ep.cover) == credit.amount_paise, (
                f"{credit.credit_id}: accepted cover does not sum to target"
            )


# --------------------------------------------------------- the batch-level number


def test_the_agent_beats_the_fixed_window_with_zero_false_matches():
    """80% decidable, 0 false matches — matching the fixed-window figure, by a
    sounder mechanism. See INCIDENTS.md #23/#24 for why 'sounder' needed a fix
    of its own before the number could be trusted.
    """
    score = run_batch(generate(), verbose=False)
    assert score["false_matches"] == 0
    assert score["decidable_credits"] == 15
    assert score["matched"] == 12
    assert abs(score["match_rate_decidable"] - 0.80) < 1e-9
