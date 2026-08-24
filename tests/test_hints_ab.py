"""The hint layer's usefulness and safety, measured and pinned. See INCIDENTS.md #18, #23, #25.

Two separate claims, two separate assertions:

  usefulness — a PERFECT extractor adds +0 matched credits on this batch
  safety     — a HOSTILE extractor causes 0 false matches and can only subtract

The first is a negative result about this project's own architecture. It is
pinned so that a future change which appears to improve it has to be examined:
the only way to make a hint break a tie is to weaken the containment property,
and that trade is never worth taking.

**A near-miss worth recording.** When the agent (INCIDENTS.md #23) was wired up,
the CLI counted a hint as "offered" the moment a narration was opaque — before
checking whether the episode ever reached the one branch (`TRY_BLIND`) where a
hint can act. That would have shipped a fabricated ceiling: "oracle offered 4
hints, still +0" when the oracle was in fact never consulted on 3 of those 4,
because the interval layer resolved them before a hint was ever needed.
`hints_offered` is now counted from the episode's own trace
(`Action.TRY_BLIND in episode.steps`), not from the narration's opacity, and the
true count at this batch's scale is **zero** — the oracle abstains on the one
opaque credit that reaches the blind layer (no date in "SETTLEMENT CREDIT"), and
the other credit reaching it has a non-opaque narration, so the hint layer's own
precondition excludes it before the oracle is ever asked. Reachability is scarcer
than it first appeared, and the honest number says so.
"""

from __future__ import annotations

from milaan.cli import run_batch
from milaan.eval.hints_ab import MalignProposer, NullProposer, OracleProposer
from milaan.oracle.generator import generate


def _ab(batch):
    return {
        "N": run_batch(batch, verbose=False, proposer=NullProposer()),
        "O": run_batch(batch, verbose=False, proposer=OracleProposer()),
        "M": run_batch(batch, verbose=False, proposer=MalignProposer()),
    }


def test_a_perfect_extractor_adds_nothing_and_that_is_the_finding():
    """The ceiling on any model's contribution to this workload is zero.

    Both traces are asserted, not just the headline matched count: identical
    match counts across N/O/M confirm the agent's policy is genuinely
    hint-independent (it reacts only to Outcome, never to hint content), and the
    hints_offered figures are exactly what the trace supports — not what would
    make the finding sound more impressive.
    """
    ab = _ab(generate())
    assert ab["O"]["matched"] == ab["N"]["matched"] == 12, (
        "if this changed, the interval layer, the agent's ladder, or the batch "
        "changed — re-derive INCIDENTS.md #18/#23 rather than banking a silent improvement"
    )
    assert ab["O"]["hints_offered"] == 0, (
        "at this batch's scale the oracle is never actually consulted: it "
        "abstains on the one opaque credit reaching TRY_BLIND, and the other "
        "credit reaching TRY_BLIND is not opaque at all. If this becomes nonzero, "
        "the reachability story in INCIDENTS.md #18 needs re-measuring, not just "
        "re-stating."
    )
    assert ab["N"]["opaque_narrations"] > 0, (
        "the batch must still contain narrations the grammar cannot read, or the "
        "'oracle abstains' explanation has nothing to abstain on"
    )


def test_traces_are_identical_regardless_of_proposer():
    """The agent's policy reacts to Outcome, never to hint content — verified, not assumed.

    If a proposer ever changed WHICH action the agent takes (as opposed to what
    happens inside TRY_BLIND), the agent would no longer be hint-independent by
    construction, and the +0 ceiling would need a different justification.
    """
    batch = generate()
    ab = _ab(batch)
    for i in range(len(ab["N"]["rows"])):
        actions = {cfg: ab[cfg]["rows"][i]["actions"] for cfg in ("N", "O", "M")}
        assert len(set(actions.values())) == 1, (
            f"credit {ab['N']['rows'][i]['credit_id']}: traces diverge across "
            f"proposers — {actions}"
        )


def test_a_hostile_extractor_cannot_cause_a_wrong_join():
    """Containment at batch level, not just in unit tests."""
    ab = _ab(generate())
    assert ab["M"]["false_matches"] == 0
    assert ab["M"]["accepted_covers"] <= ab["N"]["accepted_covers"], (
        "a hostile model expanded the accepted set — containment is violated"
    )


def test_grounding_rejects_every_hallucinated_claim():
    """Measured where the layer IS reachable — a larger batch still exercises it."""
    big = generate(settlements=40)
    m = run_batch(big, verbose=False, proposer=MalignProposer())
    assert m["hints_offered"] > 0, "a larger batch should still reach the hint layer"
    assert m["hint_claims_rejected"] >= 2 * m["hints_offered"], (
        "each malign hint carries at least a bogus reference and counterparty, "
        "and grounding must drop both before they reach the solver"
    )
    assert m["false_matches"] == 0


def test_the_result_holds_at_larger_scale():
    """+0 is not an artefact of an 18-credit batch."""
    big = generate(settlements=40)
    ab = _ab(big)
    assert ab["O"]["matched"] == ab["N"]["matched"]
    assert ab["M"]["false_matches"] == 0
    assert ab["M"]["accepted_covers"] <= ab["N"]["accepted_covers"]
