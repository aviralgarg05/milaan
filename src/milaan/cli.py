"""`milaan run` — the batch reconciliation loop and its scorecard.

This is the deliverable Track 04 asks for: one finance-ops loop closed across a
50+ record batch, reporting a match rate and the exceptions it could not resolve.

The scorecard leads with a number that most reconciliation demos do not print:

    FALSE MATCHES — covers reported that were not the true grouping

It is printed on every run, including when it is zero, because zero is the whole
claim. A match rate can be raised by guessing; a false-match count cannot. A
wrong join produces a reconciliation report that balances, so nothing downstream
catches it — which makes "how often were you confidently wrong" the only number
a finance reviewer actually needs, and the one an engine that guesses cannot
keep at zero.

Four verdicts, and three of them are refusals:

    MATCHED           exactly one exact cover, and it was the true grouping
    AMBIGUOUS_COVER   more than one exact cover exists — refused, both witnesses shown
    NO_COVER          no subset sums to the credit
    BUDGET_EXCEEDED   too large to decide within the budget; NOT the same as NO_COVER

The exception list is not a failure log. Every class in it is planted
deliberately by the generator and labelled in advance, so the run measures
behaviour on known-hard inputs rather than reporting whatever happened to break.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from datetime import date
from pathlib import Path

from .fees import base_fee_two_component
from .hints.grounding import Candidate, resolve
from .narration.grammar import extract
from .oracle.generator import PLANTED, Batch, batch_hash, generate
from .solver.interval import find_intervals
from .solver.subsetsum import Budget, Outcome

WINDOW_DAYS = 6


def _settling_value(net_paise: int) -> int:
    """What a transaction actually contributes to a bank credit, net of Razorpay's fee."""
    if net_paise <= 0:
        return net_paise            # a refund is deducted at face value
    return net_paise - base_fee_two_component(net_paise)


def run_batch(batch: Batch, *, budget: Budget | None = None, verbose: bool = True,
              proposer=None) -> dict:
    """Resolve every credit in the batch and score the result against the withheld key."""
    ledger = batch.ledger
    rows: list[dict] = []
    hinted = rescued = rejected_claims = 0
    started = time.perf_counter()

    for credit in batch.credits:
        vd = date.fromisoformat(credit.value_date)

        # The candidate pool is everything captured near the value date. The
        # settlement_id is never read here — that column is the answer key.
        pool = [
            Candidate(
                entity_id=r.entity_id,
                net_paise=_settling_value(r.net_paise),
                day_offset=abs((date.fromisoformat(r.captured_on) - vd).days),
            )
            for r in ledger
            if abs((date.fromisoformat(r.captured_on) - vd).days) <= WINDOW_DAYS
            and not r.on_hold
        ]

        fields = extract(credit.narration)
        t0 = time.perf_counter()

        # LAYER 1 — interval. Settlements batch by capture time, so a cover is
        # almost always a contiguous run in capture order. Linear, and specific
        # enough that a collision is informative rather than inevitable.
        ordered = sorted(pool, key=lambda c: (c.day_offset, c.entity_id))
        iv = find_intervals([c.net_paise for c in ordered], credit.amount_paise)

        layer = "interval"
        if iv.unique:
            outcome, proposed_ids, second = (
                Outcome.UNIQUE, tuple(ordered[i].entity_id for i in iv.covers[0]), ())
        elif iv.ambiguous:
            outcome, proposed_ids = Outcome.AMBIGUOUS, tuple(
                ordered[i].entity_id for i in iv.covers[0])
            second = tuple(ordered[i].entity_id for i in iv.covers[1])
        else:
            # LAYER 2 — blind cover. Only the residue reaches here, and this is
            # the only place a hint can act: it narrows the search, while the
            # verdict is still adjudicated on the full pool (hints/grounding.py).
            layer = "blind"
            hint = None
            if proposer is not None and fields.is_opaque:
                hint = proposer.hint_for(fields, vd)
                if hint is not None:
                    hinted += 1
                    rejected_claims += len(hint.rejected_claims)
            r = resolve(pool, credit.amount_paise, budget=budget, hint=hint)
            outcome, proposed_ids, second = r.outcome, r.cover, r.second_cover
            if r.used_hint:
                rescued += 1

        class _R:
            pass
        result = _R()
        result.outcome, result.cover, result.second_cover = outcome, proposed_ids, second
        elapsed_ms = (time.perf_counter() - t0) * 1000

        truth = frozenset(
            r.entity_id for r in ledger
            if r.settlement_id == credit.settlement_id and not r.on_hold
        )
        proposed = frozenset(result.cover)

        if result.outcome is Outcome.UNIQUE:
            verdict = "MATCHED" if proposed == truth else "FALSE_MATCH"
        elif result.outcome is Outcome.AMBIGUOUS:
            verdict = "AMBIGUOUS_COVER"
        elif result.outcome is Outcome.BUDGET_EXCEEDED:
            verdict = "BUDGET_EXCEEDED"
        else:
            verdict = "NO_COVER"

        rows.append({
            "credit_id": credit.credit_id,
            "amount_paise": credit.amount_paise,
            "planted": credit.planted_class,
            "verdict": verdict,
            "pool_size": len(pool),
            "cover_size": len(proposed),
            "truth_size": len(truth),
            "narration_opaque": fields.is_opaque,
            "layer": layer,
            "ms": round(elapsed_ms, 1),
        })

        if verbose:
            mark = {"MATCHED": "✓", "FALSE_MATCH": "✗✗", "AMBIGUOUS_COVER": "≡",
                    "NO_COVER": "—", "BUDGET_EXCEEDED": "?"}[verdict]
            print(f"  {mark:<2} {credit.credit_id}  ₹{credit.amount_paise/100:>12,.2f}  "
                  f"pool={len(pool):>3}  {verdict:<16} planted={credit.planted_class}")

    wall = time.perf_counter() - started
    verdicts = Counter(r["verdict"] for r in rows)
    # Three planted classes are *correctly* refused: a credit whose member was
    # withheld has no findable cover, identical amounts genuinely admit several,
    # and a zero-net member makes every cover non-unique. Counting those as
    # misses would penalise the engine for being right, so they are reported
    # separately rather than folded into either number.
    UNDECIDABLE = ("OUT_OF_WINDOW", "AMBIGUOUS_COVER", "ZERO_NET")
    decidable = [r for r in rows if r["planted"] not in UNDECIDABLE]
    undecidable = [r for r in rows if r["planted"] in UNDECIDABLE]
    correctly_refused = sum(
        1 for r in undecidable
        if r["verdict"] in ("AMBIGUOUS_COVER", "NO_COVER", "BUDGET_EXCEEDED"))

    return {
        "rows": rows,
        "verdicts": dict(verdicts),
        "total_credits": len(rows),
        "total_ledger_rows": len(ledger),
        "matched": verdicts["MATCHED"],
        "false_matches": verdicts["FALSE_MATCH"],
        "match_rate": verdicts["MATCHED"] / len(rows) if rows else 0.0,
        "match_rate_decidable": (
            sum(1 for r in decidable if r["verdict"] == "MATCHED") / len(decidable)
            if decidable else 0.0
        ),
        "wall_seconds": round(wall, 2),
        "credits_per_second": round(len(rows) / wall, 1) if wall else 0.0,
        "decidable_credits": len(decidable),
        "undecidable_credits": len(undecidable),
        "correctly_refused": correctly_refused,
        "hints_offered": hinted,
        "hints_rescued": rescued,
        "hint_claims_rejected": rejected_claims,
        "opaque_narrations": sum(1 for r in rows if r["narration_opaque"]),
        "accepted_covers": frozenset(
            (r["credit_id"], r["verdict"]) for r in rows if r["verdict"] == "MATCHED"),
        "by_layer": dict(Counter(r["layer"] for r in rows)),
        "by_planted_class": {
            cls: dict(Counter(r["verdict"] for r in rows if r["planted"] == cls))
            for cls in sorted({r["planted"] for r in rows})
        },
    }


def print_scorecard(score: dict, batch: Batch) -> None:
    w = 74
    print("\n" + "═" * w)
    print("  MILAAN SCORECARD")
    print("═" * w)
    print(f"  batch            seed={batch.seed}  sha256={batch_hash(batch)[:16]}…")
    print(f"  scale            {score['total_credits']} bank credits over "
          f"{score['total_ledger_rows']} ledger rows")
    print(f"  throughput       {score['credits_per_second']} credits/sec "
          f"({score['wall_seconds']}s wall)")
    print("─" * w)
    print(f"  MATCH RATE       {score['match_rate']:.1%}  "
          f"({score['matched']}/{score['total_credits']})")
    print(f"  … on decidable credits        {score['match_rate_decidable']:.1%}  "
          f"({score['matched']}/{score['decidable_credits']})")
    print(f"  CORRECTLY REFUSED {score['correctly_refused']}/{score['undecidable_credits']}"
          "  planted-undecidable credits where refusing IS the right answer")
    print()
    fm = score["false_matches"]
    banner = "  FALSE MATCHES    %d%s" % (fm, "   ← a wrong join was reported" if fm else
                                          "   ← no wrong join was ever reported")
    print(banner)
    print("─" * w)
    print("  EXCEPTIONS IT COULD NOT RESOLVE")
    for verdict, count in sorted(score["verdicts"].items()):
        if verdict in ("MATCHED", "FALSE_MATCH"):
            continue
        print(f"    {verdict:<18} {count:>3}")
    print("─" * w)
    print("  RESOLVED BY LAYER")
    for lname, n in sorted(score.get("by_layer", {}).items()):
        print(f"    {lname:<18} {n:>3}")
    print("─" * w)
    print("  BEHAVIOUR BY PLANTED CLASS")
    for cls, outcomes in score["by_planted_class"].items():
        detail = "  ".join(f"{v}={n}" for v, n in sorted(outcomes.items()))
        print(f"    {cls:<18} {detail}")
        print(f"      {PLANTED[cls]}")
    print("═" * w)
    if fm == 0:
        print("  Every reported cover was the true grouping. Refusals are refusals,")
        print("  not silent guesses — that is the claim the arithmetic guarantees.")
    else:
        print(f"  {fm} wrong join(s) reported. This is a defect, not a metric.")
    print("═" * w + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="milaan", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="reconcile a batch and print the scorecard")
    run.add_argument("--seed", type=int, default=20260823)
    run.add_argument("--settlements", type=int, default=18)
    run.add_argument("--quiet", action="store_true", help="scorecard only")
    run.add_argument("--json", type=Path, help="write the full result to a file")

    ab = sub.add_parser("hints", help="A/B the hint layer: none vs perfect vs hostile")
    ab.add_argument("--seed", type=int, default=20260823)
    ab.add_argument("--settlements", type=int, default=18)

    gen = sub.add_parser("generate", help="write a sealed batch and print its hash")
    gen.add_argument("--seed", type=int, default=20260823)
    gen.add_argument("--settlements", type=int, default=18)
    gen.add_argument("--out", type=Path, default=Path("results/batch.json"))

    args = parser.parse_args(argv)
    batch = generate(args.seed, settlements=args.settlements)

    if args.command == "hints":
        from .eval.hints_ab import CONFIGS
        w = 78
        print(f"\nMILAAN · hint-layer A/B on {len(batch.credits)} credits "
              f"(seed {batch.seed})\n")
        results = {}
        for cfg in CONFIGS:
            r = run_batch(batch, verbose=False, proposer=cfg.proposer)
            results[cfg.key] = r
            print(f"  {cfg.proposer.name}")
            print(f"    matched {r['matched']:>2}/{r['total_credits']}   "
                  f"decidable {r['match_rate_decidable']:>6.1%}   "
                  f"false-matches {r['false_matches']}   "
                  f"hints offered {r['hints_offered']:>2}  rescued {r['hints_rescued']}  "
                  f"claims rejected {r['hint_claims_rejected']}")
        n, o, m = results["N"], results["O"], results["M"]
        print("\n" + "═" * w)
        print("  USEFULNESS — what a PERFECT extractor adds")
        print("═" * w)
        delta = o["matched"] - n["matched"]
        print(f"    baseline (no hints)          {n['matched']}/{n['total_credits']} matched")
        print(f"    oracle (perfect extractor)   {o['matched']}/{o['total_credits']} matched")
        print(f"    CEILING ON ANY MODEL         {delta:+d} credits")
        print(f"    {o['opaque_narrations']} narrations were opaque to the grammar; "
              f"{o['hints_offered']} received a hint")
        print("\n" + "═" * w)
        print("  SAFETY — what a COMPROMISED extractor subtracts")
        print("═" * w)
        subset = m["accepted_covers"] <= n["accepted_covers"]
        print(f"    malign false-matches         {m['false_matches']}"
              f"   {'(zero, as the containment property requires)' if not m['false_matches'] else '  ← CONTAINMENT VIOLATED'}")
        print(f"    malign accepted ⊆ baseline   {subset}"
              f"   {'(a hostile model can only subtract)' if subset else '  ← CONTAINMENT VIOLATED'}")
        print(f"    hallucinated claims rejected {m['hint_claims_rejected']} "
              f"(grounding dropped every one before it reached the solver)")
        print(f"    credits lost to hostility    {n['matched'] - m['matched']}")
        print("═" * w + "\n")
        return 0 if (m["false_matches"] == 0 and subset) else 1

    if args.command == "generate":
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(batch.to_dict(withhold_answers=True), indent=1))
        print(f"batch     {len(batch.credits)} credits, {len(batch.ledger)} ledger rows")
        print(f"seed      {batch.seed}")
        print(f"sha256    {batch_hash(batch)}")
        print(f"written   {args.out}  (answer key withheld)")
        return 0

    if not args.quiet:
        print(f"\nMILAAN · reconciling {len(batch.credits)} bank credits "
              f"against {len(batch.ledger)} ledger rows\n")
    score = run_batch(batch, verbose=not args.quiet)
    print_scorecard(score, batch)

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(
            {"seed": batch.seed, "batch_sha256": batch_hash(batch), **score}, indent=1))
        print(f"  full result → {args.json}\n")

    return 1 if score["false_matches"] else 0


if __name__ == "__main__":
    sys.exit(main())
