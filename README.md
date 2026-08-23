# MILAAN

**A bank credit lands as one lump sum with a mangled narration and no usable
reference. MILAAN reconstructs which payments, refunds, fees and GST compose it —
to the paise — and refuses rather than guesses when more than one answer fits.**

Razorpay AI Buildathon 2026 · **Track 04 — AI Finance Controller**

> **बैंक मिलान विवरण** *(bank milan vivran)* is one of the two standard Hindi
> terms for **Bank Reconciliation Statement**; Tally's Hindi documentation uses
> *मिलान करना* for reconciling an account against a passbook. मिलान — matching,
> tallying — is the accounting sense, distinct from मिलन, meeting.
>
> In fairness: the name came out of the idea-generation pass, and the fit was
> noticed afterwards. It is a good fit and not a clever one.

---

## Start here

```bash
uv run --with openpyxl --with-editable . python -m milaan.cli run
```

No API key. No Docker. No network. It reconciles 18 bank credits against 237
ledger rows and prints:

```
  MATCH RATE       66.7%  (12/18)
  … on decidable credits        80.0%  (12/15)
  CORRECTLY REFUSED 3/3  planted-undecidable credits where refusing IS the right answer

  FALSE MATCHES    0   ← no wrong join was ever reported
```

**The number that matters is the third one.** A match rate can be raised by
guessing; a false-match count cannot. A wrong join produces a reconciliation
report that balances, so nothing downstream ever catches it — which makes "how
often were you confidently wrong" the only figure a finance reviewer needs.

Three of the eighteen credits are *structurally* undecidable — a member withheld
from the export, or a fee-only row netting to zero, which gives every cover 2^k
variants. Refusing those is the correct answer and MILAAN refused all three. The
other three refusals are genuine ambiguities it declined to guess at. Full
caveats in [`LIMITS.md`](LIMITS.md).

### The LLM layer contributes nothing here, and that is measured

```bash
uv run --with openpyxl --with-editable . python -m milaan.cli hints
```

Three configurations on the same batch: no hints, a **perfect** extractor, and a
**hostile** one. The oracle reads the capture date with 100% accuracy, so no real
model can beat it — its score is the *ceiling* on what any model could add.

```
  CEILING ON ANY MODEL         +0 credits
  malign false-matches          0
  malign accepted ⊆ baseline    True
```

Two separate facts, and they are worth keeping apart:

**Measured.** After the capture-time fix ([#19](INCIDENTS.md)) the interval layer
resolves 16 of 18 credits, so only two reach the blind layer where a hint could
act — and neither carries an opaque narration. The oracle was offered **zero
lines**. The layer is not merely unhelpful here; it is never invoked.

**Predicted, not demonstrated by that run.** Had it been invoked, containment
says it still could not have raised the match rate: uniqueness is adjudicated on
the full pool, so a hint can never break a genuine tie. That argument rests on
the malign configuration and the 33 containment tests, not on the +0 above — the
+0 is a fact about reachability.

That is [incident #18](INCIDENTS.md). The zero is published rather than
engineered away: the only route to a positive number is weakening containment,
which buys it with the wrong joins this project exists to prevent.

The test suite is the other half of the argument:

```bash
uv run --with pytest --with openpyxl --with-editable . pytest tests/ -q
```

Its first test is the foundation:

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
| **Interval** | Prefix sums over capture-time-ordered candidates. | O(n) | **ships** — resolves 16 of 18 |
| **Perturbed interval** | Interval ± a bounded set of exclusions/carry-ins. | bounded | not built — diagnosed as the wrong fix (#19) |
| **Blind cover** | Signed subset-sum, bitset DP over paise. | pseudo-poly | **ships** |

The interval layer and the blind solver ship. The anchor join and
perturbed-interval do not — see the status table below and `LIMITS.md`.

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

MILAAN has two answers and they apply to different data. Being precise about
which is which matters more than either one.

**On Razorpay's published sample reports, the answer key really is theirs.**
Razorpay grouped those settlements years before this project existed. When the
closure identity holds to the paise on all three complete settlements, that is a
property of *their* ledger. That leg is externally authored and needs no defence.

**On the generated batch — the one every headline number comes from — it is
not.** The generator assigns the entity ids, the timestamps and the grouping.
Razorpay authors only the fee *formula*, and that formula is the one thing in the
answer key measured from their real engine (25 of 25 charges, INCIDENTS.md #16).
Claiming external authorship of the grouping here would be false, and an earlier
version of this section did claim it.

What actually defends the generated batch is weaker and sufficient: exact cover
is **self-certifying**. A proposed grouping sums to the paise or it does not.
Neither the author nor a model can fudge a match into existence, which is why
the number worth reading is not the match rate but the **zero false matches** —
that one cannot be inflated by a generous generator.

Full provenance — what is Razorpay's, what is published, and what is mine and
labelled as mine — is in [`DATA.md`](DATA.md).

## What broke

[`INCIDENTS.md`](INCIDENTS.md) — written as it happened, with commit hashes and
the regression test that pins each one. **Twenty-one entries**, and the pattern in
them is the point: six are cases where the thing that broke was my own
conclusion rather than my code.

A floating-point hazard I asserted without measuring, and that measurement showed
**does not exist** (#6). A test that called a cover unique when the solver was
right to call it ambiguous (#7). A solver that returned UNIQUE on a provably
ambiguous input, which 100+ property tests missed because **no generator I wrote
ever sampled a zero** (#14). A fee anomaly I proved was not a single rate, then
stopped — it was two rates, and someone else found it (#16). A 0% first run that
was the solver being correct and my architecture being wrong (#17). A test class
named after an outcome its construction could not guarantee, which had been
quietly grading the engine on a curve (#20).

## Status

| | |
|---|---|
| Integer paise + boundary adapters | done, property-tested |
| Razorpay report parsers (3 dialects) | done, traps pinned |
| Closure identity on Razorpay's own data | **done, passing** |
| Signed subset-sum + uniqueness + budget | done, verified vs brute force |
| Narration grammar | **done** |
| LLM hint layer + containment property | **done**, 33 tests |
| Interval layer | **done** — carries 16 of 18 credits |
| Sealed ground-truth generator | **done**, seed + digest pinned in the test suite |
| Batch runner, match rate, exception list | **done** — `milaan run` |
| Hint-layer A/B (none / perfect / hostile) | **done** — `milaan hints`, ceiling is +0 |
| Anchor layer (UTR → settlement join) | **not built** — see LIMITS.md |
| Perturbed-interval layer | **not built** — diagnosed as the wrong fix, see #19 |
| 5-minute pitch video | **not started** |

Both hint-layer claims now have numbers: containment holds under an adversary at
every scale tested, and the usefulness ceiling is **+0**. They are reported as
two separate figures because conflating them is how "we used AI" comes to mean
nothing.

Licence: MIT.
