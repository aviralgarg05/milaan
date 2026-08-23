# MILAAN

**A bank credit lands as one lump sum with a mangled narration and no usable
reference. MILAAN reconstructs which payments, refunds, fees and GST compose it —
to the paise — and refuses rather than guesses when more than one answer fits.**

Razorpay AI Buildathon 2026 · **Track 04 — AI Finance Controller**

---

## Start here

```bash
uv run --with pytest --with openpyxl --with-editable . pytest tests/ -q
```

No API key. No Docker. No network. The first test is the argument:

```
setl_Jq0XZksg0i2Fat   +99p +99p                        = 198p   vs settlement debit 198p  ✓
setl_JtAs2E7Uf55JMV   +99p ×5  −100p (refund)          = 395p   vs settlement debit 395p  ✓
setl_JvXyfCc3YcAT6V   +99p +99p                        = 198p   vs settlement debit 198p  ✓
setl_K4eBPTyLTnLCGr   +99p  … but declared 191p        → OUT_OF_WINDOW
```

That is **Razorpay's own published `sample-combined-report.xlsx`**, downloaded
verbatim from their docs and vendored under `data/razorpay-samples/` with source
URLs in `SOURCES.md`. The closure identity —

> `Σ(member credits) − Σ(member debits) == settlement debit`, in integer paise

— holds exactly on all three complete settlements, including the one that nets a
refund against five payments. The fourth does not close, and that is not a defect
in the data: it is a host-authored instance of MILAAN's `OUT_OF_WINDOW` exception
class, sitting in the sample for free. **The exception taxonomy was validated
against someone else's data before a line of solver existed.**

## The problem

A merchant's bank statement shows one credit: `₹8,36,833.41`,
`NEFT-HDFC0000123-RAZORPAY SOFTWARE-N2938471`. Razorpay's dashboard shows 340
individual payments, some refunds, per-transaction fees and GST. Which
transactions make up that credit?

Today this is done by hand, or not at all. It matters because the join is how a
merchant knows they were paid what they were owed — and because a *wrong* join is
worse than no join. A wrong join produces a clean-looking reconciliation report
that balances, so nothing downstream ever catches it. It is a silent financial
misstatement.

## Why this is not just fuzzy matching

Settlements batch by capture time, so a cover is usually an **interval** in time
order — but not always, because held payments drop out and late ones roll in. So
the solver is layered, cheapest first:

| Layer | Method | Cost | Status |
|---|---|---|---|
| **Anchor** | UTR in the narration → settlement id. No search. | O(1) | grammar ships; join not built |
| **Interval** | Prefix sums over time-ordered candidates. | O(n) | **not built** |
| **Perturbed interval** | Interval ± a bounded set of exclusions/carry-ins. | bounded | **not built** |
| **Blind cover** | Signed subset-sum, bitset DP over paise. | pseudo-poly | **ships** |

Only the blind-cover layer and the narration grammar exist today. The cheap
layers above it are the plan, not the product, and this table says so rather
than describing them in the present tense.

Refunds subtract, so the blind layer shifts the signed problem to a non-negative
one using

```
T + Σ|neg|  =  Σ(chosen positives) + Σ(unchosen negatives)
```

which lets a pure-positive bitset DP answer the signed question exactly, reading
the negative half of the answer off by complement.

**Uniqueness is verified, not assumed.** Finding *a* cover is not enough — the
solver pins each member of the first solution out in turn and re-solves, so
`UNIQUE` means "no second cover exists", not "I stopped looking". When a second
cover does exist the verdict is `AMBIGUOUS_COVER` and MILAAN returns **both
witnesses** so the refusal is explainable.

That is the common case, not an edge case. A subscription merchant charging one
price has many identical amounts; Razorpay's own sample is five identical 99p
payments, and every proper subset of those is genuinely undecidable from amounts
alone.

`BUDGET_EXCEEDED` is a fourth outcome, distinct from `NONE`. Subset-sum is
NP-complete, so a large enough problem is **declined and counted** rather than
hung on — we never report "no cover" for a problem we chose not to decide.

## Where an LLM is used, and where it deliberately is not

**Not used — the solver, the oracle, the fee model, the verdict.** These are
arithmetic. A reconciliation engine that returns a different answer on the same
input is not a financial control, and a model cannot make a subset sum correctly
that does not.

**Used — narration hints, and only where the deterministic grammar found
nothing.** When no UTR, no reference and no parseable structure can be extracted
from a bank narration string, an LLM proposes hints that *narrow the candidate
set* — a probable date window, a probable counterparty. The proposer, the typed
hint schema, the grounding check and the containment tests all ship; what does
not yet exist is the batch runner that would report how often it helps.

The containment property is the point, and it ships as a test:

> for **any** LLM output, including deliberately hallucinated output, the
> accepted match set is a subset of the arithmetically verifiable match set.

The model can only reduce the exception count. It cannot cause a wrong join.
That property is proved by construction in `hints/grounding.py` and exercised in
`tests/test_hint_containment.py` against hallucinated references, injected
instructions and adversarial garbage — including a narration carrying a prompt
injection, since the narration is attacker-controlled in the real world.

## Ground truth, and how it avoids being circular

The attack that kills most reconciliation demos is: *you generated the data, so
you generated the answer key, so your match rate measures your generator.*

MILAAN's answer is that **it authors the inputs and Razorpay authors the
answers.** Razorpay independently assigns entity ids, `fee`, `tax`, capture
timestamps and the settlement grouping. The `settlement_id` column is stripped
before the solver ever sees it, and the solver's proposed cover is graded by set
equality against the withheld column. MILAAN never decides which payment belongs
to which settlement.

Underneath that sits a leg that survives even if the first fails entirely: exact
cover is **self-certifying**. A proposed grouping sums to the paise or it does
not. Neither the author nor a model can fudge a match into existence.

Full provenance — what is Razorpay's, what is published, and what is mine and
labelled as mine — is in [`DATA.md`](DATA.md).

## What broke

[`INCIDENTS.md`](INCIDENTS.md) — written as it happened, with commit hashes and
the regression test that pins each one. Seven entries so far. Two of them are my
own tests being wrong rather than my code, including one where I asserted a
floating-point hazard that measurement showed **does not exist** at settlement
scale, and said so instead of quietly deleting the test.

## Status

| | |
|---|---|
| Integer paise + boundary adapters | done, property-tested |
| Razorpay report parsers (3 dialects) | done, traps pinned |
| Closure identity on Razorpay's own data | **done, passing** |
| Signed subset-sum + uniqueness + budget | done, verified vs brute force |
| Narration grammar | **done** |
| LLM hint layer + containment property | **done**, 33 tests |
| Interval & perturbed-interval layers | **not started** |
| Sealed ground-truth generator | **not started** |
| Batch runner, match rate, exception list | **not started** — this is the Track 04 deliverable |
| 5-minute pitch video | **not started** |

**What this repo cannot do yet:** run a batch, report a match rate, or emit an
exception list. Those are what Track 04 actually grades, and they are the next
and largest piece of work. Everything above is the machinery they will be built
on, not a substitute for them.

Licence: MIT.
