"""The scorecard, pinned. This is the number the submission reports.

A match rate that drifts silently is worse than no match rate, so the headline
figures are asserted here rather than only printed. If a change moves them, the
suite says so and the change has to be deliberate.

The claim these tests pin is deliberately narrow and is stated the same way in
LIMITS.md: *given a ledger and a set of credits grouped by a documented rule,
the solver recovers the grouping on 75% of decidable credits, correctly refuses
100% of the planted-undecidable ones, and never reported a wrong join.* The last
clause is the one the arithmetic guarantees; the first two are measurements.
"""

from __future__ import annotations

from milaan.cli import run_batch
from milaan.oracle.generator import PLANTED, batch_hash, generate


def test_the_batch_clears_track_04s_stated_scale():
    batch = generate()
    assert len(batch.ledger) >= 50, "Track 04 asks for a 50+ record batch"
    assert len(batch.credits) >= 15
    assert {c.planted_class for c in batch.credits} == set(PLANTED), (
        "every exception class must be planted deliberately, not left to chance"
    )


def test_the_batch_is_deterministic_and_hash_stable():
    """The seal. A batch tuned after seeing results cannot pass as the original."""
    a, b = generate(20260823), generate(20260823)
    assert batch_hash(a) == batch_hash(b)
    assert batch_hash(generate(1)) != batch_hash(a)


def test_no_wrong_join_is_ever_reported():
    """THE claim. A match rate can be raised by guessing; this cannot."""
    score = run_batch(generate(), verbose=False)
    assert score["false_matches"] == 0, (
        f"{score['false_matches']} wrong join(s) — this is a defect, not a metric"
    )


def test_headline_figures_are_what_the_submission_reports():
    score = run_batch(generate(), verbose=False)
    assert score["total_credits"] == 18
    assert score["total_ledger_rows"] == 269
    assert score["matched"] == 9
    assert score["decidable_credits"] == 12
    assert abs(score["match_rate_decidable"] - 0.75) < 1e-9
    assert score["correctly_refused"] == score["undecidable_credits"] == 6


def test_every_planted_undecidable_credit_is_refused_not_guessed():
    """Refusing is the correct answer for these, and being right must not look like a miss."""
    score = run_batch(generate(), verbose=False)
    for cls in ("AMBIGUOUS_COVER", "ZERO_NET", "OUT_OF_WINDOW"):
        outcomes = score["by_planted_class"][cls]
        assert "MATCHED" not in outcomes, (
            f"{cls} is undecidable by construction; a MATCHED here would be luck"
        )
        assert "FALSE_MATCH" not in outcomes


def test_the_interval_layer_carries_most_of_the_load():
    """INCIDENTS.md #17: structure decides, search is the fallback for the residue."""
    score = run_batch(generate(), verbose=False)
    assert score["by_layer"]["interval"] > score["by_layer"]["blind"]


def test_blind_search_alone_would_report_nothing_but_ambiguity():
    """The measurement behind #17, kept as a test so the claim stays checkable.

    Disabling the interval layer and running the blind solver on the same pools
    reproduces the original result: 18 of 18 ambiguous, match rate zero. With
    ~200 candidates there are 2^200 subsets and ~10^7 achievable sums in range,
    so collisions are guaranteed by pigeonhole. Exact-cover search alone is not
    a reconciliation strategy.
    """
    from datetime import date

    from milaan.cli import WINDOW_DAYS, _settling_value
    from milaan.hints.grounding import Candidate, resolve
    from milaan.solver.subsetsum import Outcome

    batch = generate()
    unique = ambiguous = 0
    for credit in batch.credits[:6]:          # a sample; the full run takes ~3s
        vd = date.fromisoformat(credit.value_date)
        pool = [
            Candidate(r.entity_id, _settling_value(r.net_paise),
                      abs((date.fromisoformat(r.captured_on) - vd).days))
            for r in batch.ledger
            if abs((date.fromisoformat(r.captured_on) - vd).days) <= WINDOW_DAYS
            and not r.on_hold
        ]
        assert len(pool) > 100, "the point only holds at realistic pool size"
        out = resolve(pool, credit.amount_paise).outcome
        unique += out is Outcome.UNIQUE
        ambiguous += out is Outcome.AMBIGUOUS

    assert ambiguous == 6 and unique == 0, (
        "blind search on a 200-candidate pool should be uniformly ambiguous; "
        f"got {ambiguous} ambiguous, {unique} unique"
    )
