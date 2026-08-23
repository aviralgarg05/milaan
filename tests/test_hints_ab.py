"""The hint layer's usefulness and safety, measured and pinned. See INCIDENTS.md #18.

Two separate claims, two separate assertions:

  usefulness — a PERFECT extractor adds +0 matched credits on this batch
  safety     — a HOSTILE extractor causes 0 false matches and can only subtract

The first is a negative result about this project's own architecture. It is
pinned so that a future change which appears to improve it has to be examined:
the only way to make a hint break a tie is to weaken the containment property,
and that trade is never worth taking.
"""

from __future__ import annotations

import pytest

from milaan.cli import run_batch
from milaan.eval.hints_ab import MalignProposer, NullProposer, OracleProposer
from milaan.oracle.generator import generate


@pytest.fixture(scope="module")
def ab():
    batch = generate()
    return {
        "N": run_batch(batch, verbose=False, proposer=NullProposer()),
        "O": run_batch(batch, verbose=False, proposer=OracleProposer()),
        "M": run_batch(batch, verbose=False, proposer=MalignProposer()),
    }


def test_a_perfect_extractor_adds_nothing_and_that_is_the_finding(ab):
    """The ceiling on any model's contribution to this workload is zero."""
    assert ab["O"]["matched"] == ab["N"]["matched"], (
        "if the oracle now helps, the interval layer or the budget changed — "
        "re-derive INCIDENTS.md #18 rather than quietly banking the improvement"
    )
    assert ab["O"]["hints_offered"] > 0, "the oracle must actually be offering hints"


def test_a_hostile_extractor_cannot_cause_a_wrong_join(ab):
    """Containment at batch level, not just in unit tests."""
    assert ab["M"]["false_matches"] == 0
    assert ab["M"]["accepted_covers"] <= ab["N"]["accepted_covers"], (
        "a hostile model expanded the accepted set — containment is violated"
    )


def test_grounding_rejects_every_hallucinated_claim(ab):
    """The malign proposer invents a UTR and a counterparty on every call."""
    assert ab["M"]["hint_claims_rejected"] >= 2 * ab["M"]["hints_offered"], (
        "each malign hint carries at least a bogus reference and counterparty"
    )
    assert ab["O"]["hint_claims_rejected"] == 0, "the oracle never hallucinates"


def test_the_result_holds_at_larger_scale(ab):
    """+0 is not an artefact of an 18-credit batch."""
    big = generate(settlements=40)
    n = run_batch(big, verbose=False, proposer=NullProposer())
    o = run_batch(big, verbose=False, proposer=OracleProposer())
    m = run_batch(big, verbose=False, proposer=MalignProposer())
    assert o["matched"] == n["matched"]
    assert m["false_matches"] == 0
    assert m["accepted_covers"] <= n["accepted_covers"]
