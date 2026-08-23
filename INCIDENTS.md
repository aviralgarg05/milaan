# Incidents

What broke, and how I got out. Written as it happened, not reconstructed.

Every entry carries the symptom, the cause, the commit that fixed it, and the
regression test that now pins it. Entries stay even when the finding was that I
was wrong — especially then.

---

### #1 — `groupby('settlement_id')` loses every settlement total

**Date** 21 Aug · **Fixed in** `ea55d9f` · **Pinned by** `test_settlement_rows_do_not_carry_their_own_settlement_id`

**Symptom.** My first pass at the closure identity reported `NO-SETTLEMENT-ROW`
for all four settlements, and one spurious bucket keyed `None` holding a total
of 198p with zero members. Every group looked like it was missing its total.

**Cause.** In a Razorpay combined report a settlement row's own identifier lives
in `entity_id`, and its `settlement_id` column is null. Member rows point *up* to
the settlement via `settlement_id`. So grouping the whole file by
`settlement_id` collects every settlement row into a single `None` bucket and
leaves each real group headless. The obvious one-liner produces a confidently
wrong answer rather than an error.

**Fix.** Two separate accessors that cannot be confused: `group_by_settlement()`
keys members by `settlement_id` and explicitly excludes settlement rows;
`settlement_rows()` keys totals by `entity_id`. The test asserts `None` is never
a key and no member is itself a settlement.

---

### #2 — a blank column A silently shifts every field

**Date** 21 Aug · **Fixed in** `ea55d9f` · **Pinned by** `test_settlements_report_has_a_blank_column_a`

**Symptom.** `sample-settlements-report.xlsx` parsed without error and produced
nonsense — the settlement id landed in the amount field.

**Cause.** The file's headers start at **B1**, not A1, and it carries 19 trailing
all-`None` columns. Anything that reads by ordinal position — `read_excel` with
default arguments included — shifts every column by one. This does not raise. It
succeeds, with all the data in the wrong fields, which is worse.

**Fix.** The loader locates the header row as the first row with more than two
populated cells, then indexes strictly by *header position*, discarding columns
with no header. Ordinals are never used.

---

### #3 — one column, two Python types, three date formats

**Date** 21 Aug · **Fixed in** `ea55d9f` · **Pinned by** `test_date_columns_mix_datetime_and_str_in_the_same_column`

**Symptom.** `AttributeError: 'datetime.datetime' object has no attribute 'strip'`
partway through the batch — after several rows had already parsed fine.

**Cause.** `created_at` in Razorpay's sample holds native `datetime` objects
*and* strings, in the same column. Measured across the file's two date columns
there are 18 distinct (column, type, value) shapes, with strings in three
formats: `2022-04-07 10:43:32`, `14/07/2022 10:01:14`, and `14-07-2022`.

**Fix.** `reports/dates.py` dispatches on type first, then tries an ordered list
of day-first formats. It never raises — an unparseable cell yields
`ParsedDate(value=None)` with the original preserved, so one bad timestamp
becomes a named exception downstream instead of killing a 340-row batch.

**The part that isn't fixed, by choice.** `07/04/2022` is genuinely ambiguous.
MILAAN reads day-first (Indian convention) and *counts* every value that could
have been read either way. The count is reported per run. A settlement window
that is off by a month changes which payments are candidates for a cover, so
this is surfaced rather than resolved by guessing.

---

### #4 — the UTR column exists but the data doesn't

**Date** 21 Aug · **Fixed in** `ea55d9f` · **Pinned by** `test_settlement_utr_is_null_in_every_row_of_the_combined_report`

**Symptom.** The anchor pass — match a bank credit to a settlement by UTR, skip
the solver entirely — had nothing to match on. 0 of 14 rows carried a UTR.

**Cause.** `settlement_utr` is a real column in the combined report and is null
in every row of Razorpay's published sample. The UTR lives only in the
*settlements* report, under the plain name `utr`. The two files are not
interchangeable, though they look it.

**Fix.** The anchor pass joins combined → settlements to recover a UTR. Noted
for later: the API's `/v1/settlements/recon/combined` *does* return
`settlement_utr`, so the API path and the XLSX path need different join
strategies. Both mappers ship; neither is assumed.

---

### #5 — 18% GST on a one-paisa fee is zero

**Date** 21 Aug · **Fixed in** `ea55d9f` · **Pinned by** `test_eighteen_percent_gst_on_a_one_paisa_fee_rounds_to_zero`

**Symptom.** A fee model applying the published 18% GST rate produced totals a
paise off from the sample data.

**Cause.** Every payment in Razorpay's sample carries `fee = 1p, tax = 0p`.
Eighteen percent of one paisa is 0.18p, which rounds to zero. Razorpay rounds
tax **per transaction**, not per settlement, so a model that applies the rate to
an aggregate diverges.

**Why it matters more than a paise.** A cover either closes exactly or it does
not. A one-paisa modelling error does not produce a slightly-wrong answer; it
produces an unexplained exception on an otherwise correct match.

**Fix.** The fee model's residual against Razorpay's actual returned `fee`/`tax`
is reported as a number rather than absorbed, and any remainder becomes a named
exception class.

---

### #6 — I asserted a float hazard that does not exist

**Date** 21 Aug · **Fixed in** *(pending)* · **Pinned by** `test_the_float_hazard_is_conversion_not_accumulation`

**Symptom.** My own test failed: I wrote `assert 0.99*5 - 1.00 != 3.95` to
demonstrate why money must be integer paise. It *is* exactly 3.95. So is the
repeated-addition form.

**Cause.** I had the right conclusion and the wrong reason. I measured it
properly: across 2,000 randomised settlements of 340 rows, float summation
agreed with `Decimal` to the paise **every time**. A double carries ~15
significant digits and a settlement total is ~8, so accumulation error stays far
below a paise. **The accumulation hazard is not real at this scale, and MILAAN
does not claim it is.**

The hazard that *is* real is the conversion at the boundary. `int(r * 100)`
truncates, and binary floating point puts **4,586 of the first 99,999** paise
values just below their integer: ₹0.29 → 28p, ₹8.20 → 819p. A 4.6% corruption
rate on the most natural one-liner anyone would write, every failure short by
exactly one paise — precisely the error that turns a valid cover into an
unexplained exception.

**Fix.** The test now asserts what is true and documents what is not. Integer
paise are justified by the boundary conversion, not by the arithmetic, and
`from_report_rupees` routes through `Decimal(str(x))` for that reason.

**Why this entry stays.** The whole project claims to prefer an honest exception
over a confident guess. A test that asserts a hazard I had not measured is that
failure in miniature, in my own code, on day one.

---

### #7 — my test was wrong and the solver was right

**Date** 21 Aug · **Pinned by** `test_finds_a_simple_unique_cover`

**Symptom.** First run of the solver suite failed immediately. I had written
`solve([99, 99, 250, 700], 349)` and asserted `UNIQUE`. The solver returned
`AMBIGUOUS` with witnesses `(0, 2)` and `(1, 2)`.

**Cause.** The solver was correct and I was not. Two 99p items are
interchangeable, so 99+250 and 99′+250 are two genuinely distinct covers of 349p.
I had reached for a "simple" fixture without checking whether my own example was
decidable.

**Why it is worth a numbered entry.** This is the project's central claim
demonstrating itself against its author. Ambiguity is not an edge case bolted on
for completeness — it is the *default* in Indian subscription and D2C merchants,
where many transactions share one price. Razorpay's own published sample is five
identical 99p payments, and every proper subset of those is ambiguous by
construction. A matcher tuned to always return an answer would have silently
returned `(0, 2)` here, produced a clean-looking report, and mis-stated which
payment settled — the exact failure no downstream audit catches.

Two of the first seven incidents in this log are my tests being wrong rather
than my code. That is what it looks like to write the oracle before the
implementation and then actually believe it.

**Fix.** The test uses distinct amounts and asserts `second_solution == ()`. The
ambiguous case moved to its own test, where it is the point rather than an
accident.

---

### #8 — `GET /orders` is eventually consistent, and a minting harness will believe it

**Date** 23 Aug · **Found by** `scripts/check_keys.py` write probe

**Symptom.** Created `order_TTGXsvW1pVeluE`, got a `200` with the order body
back, then immediately listed `GET /v1/orders?count=3` — **0 items**. The order
appeared to have vanished the instant after it was created.

**Cause.** Not vanished, not indexed. Fetching the same order by id returned it
immediately and correctly; only the *list* endpoint lagged, by roughly a second.
Razorpay's collection endpoints are eventually consistent with respect to writes,
while point reads are not.

**Why this is dangerous specifically for MILAAN.** The minting harness creates a
few hundred transactions and then reads the ledger back to build the candidate
pool. A read-after-write against a list endpoint will silently return a *short*
pool. The solver would then be handed a candidate set missing the very
transactions that compose the target credit, and would report `NO_COVER` —
a fabricated exception, attributed to the solver, caused by the harness. That is
the worst class of bug this project can have: it degrades the headline metric
while looking like a genuine finding.

**Fix (planned).** The minting harness records every entity id it creates at
creation time and reconciles that registry against the list endpoint, polling
until the two agree, with a timeout that raises rather than proceeding on a
short pool. Point reads by id are the source of truth; list endpoints are
treated as an index that may lag. No batch is allowed into an eval run until its
registry reconciles exactly.

**Wider note.** This is why `check_keys.py` exists as a probe rather than an
assumption. Nothing in Razorpay's documentation states the consistency model of
the collection endpoints; it took a write and an immediate read to find it, on
the first day the keys existed.

---

### #9 — the industry-standard test card is not a Razorpay test card

**Date** 23 Aug · **Fixed in** `data/test-cards.md`

**Symptom.** First attempt to capture a test payment failed with
*"International cards are not supported. Please contact our support team for
help."* Nothing was misconfigured on the account.

**Cause.** I used `4111 1111 1111 1111` — the generic Visa test number that
works on most gateways — from memory, without checking. It is not in Razorpay's
documented domestic set, so their BIN lookup classifies it as international, and
new accounts have international payments disabled by default. Razorpay's actual
domestic test cards are `4100 2800 0000 1007` (Visa), `5500 6700 0000 1002`
(Mastercard) and `6527 6589 0000 1005` (RuPay), per
[razorpay/markdown-docs](https://github.com/razorpay/markdown-docs/blob/master/payments/payments/test-card-details.md).

**Why the error message made it worse.** "International cards are not supported"
is a plausible, actionable, *wrong* diagnosis. It points at an account setting
rather than at the card number, and the obvious next step — enabling
international payments — would not have fixed it. Ten minutes could easily have
gone into the wrong drawer.

**The useful thing this turned up.** Razorpay publishes **twenty error-scenario
cards** — ten Visa `4100 2800 000X 000Y` and ten Mastercard
`5305 6200 000X 000Y` — each producing a specific documented failure, plus the
rule that an OTP under four digits fails the payment deliberately.

That matters for MILAAN beyond unblocking the mint. Failed payments never
settle, so they must *not* appear in a candidate pool — and a candidate pool
polluted with failed payments is a realistic exception class rather than an
invented one. I can now generate that class from **Razorpay's own documented
failure modes** instead of authoring it myself, which is one more label I do not
have to be trusted about.

---

### #10 — headless minting is RED: checkout runs hCaptcha, and I will not beat it

**Date** 23 Aug · **Verdict** RED, fallback taken · **Probe** `/tmp/mint4.py`

**Symptom.** Razorpay's hosted checkout drives fine headlessly right up to
submission: the page renders, contact details fill, the Cards method opens, and
the card fields populate correctly. Clicking **Continue** then does nothing
visible. Enumerating every frame on the page found the reason:

```
[newassets.hcaptcha.com/captcha/v1/…]  "Please try again. ⚠️ | Verify | EN"
```

**Cause.** Checkout loads bot detection — invisible hCaptcha via Stripe's
`human-security` bundle, alongside a `sardine.ai` device collector. Headless
Chromium trips it. An earlier attempt using `fill()` failed for a *different*
and more mundane reason (React never sees a synthetic value assignment), so
switching to `press_sequentially` was necessary to get far enough to discover
the real blocker underneath.

**Decision: stop.** Defeating a payment provider's fraud controls to generate
demo data is out of bounds on its own terms, and it is also self-defeating here
— a submission whose data pipeline depends on evading Razorpay's bot detection
is not one you want to explain to Razorpay's panel. The 300-payment automated
pool is cut. This was pre-planned as cut-list item 5, decided on day one rather
than discovered on day eleven.

**What it actually costs, which is less than it looks.** The sealed,
hash-committed generator was already PRIMARY ground truth (`DATA.md`), chosen
before this probe rather than retreated to after it. Live minting was only ever
going to strengthen two specific things:

1. **The fee model** — and this survives intact, because it needs a *handful* of
   real captured payments, not hundreds. One already exists
   (`pay_TTGbjjcwSCSQaC`: 49900p → fee 1098p, exactly 2.200%) and a few more
   done by hand pin the rounding rule.
2. **A live Razorpay-authored settlement grouping** — which was never available
   anyway: `GET /v1/settlements` returns empty on an unactivated test account,
   settlement is T+2 working days, and no documentation says test mode produces
   settlements at all.

So the load-bearing claim is unchanged: the closure identity is validated
against **Razorpay's own published sample reports**, which are externally
authored and need no API at all.

**The honest sentence this forces, said on camera.** "The settlement groupings
in my evaluation corpus were produced by a seeded script that was sealed and
hash-committed before the solver existed — not by Razorpay's engine. The
identity that script implements is the one I verified against Razorpay's own
published sample data, and the fee model is calibrated against real captured
test payments." That is weaker than "Razorpay computed my answer key," and it is
what is true.

---

### #11 — the rate limiter does not say 429, and a naive batch loses 13 of 18

**Date** 23 Aug · **Fixed in** `scripts/mint_links.py` · **Pinned by** the registry's resume path

**Symptom.** Minting 18 payment links in a tight loop: the first five succeeded,
the remaining thirteen all failed at once.

**Cause.** `POST /v1/payment_links` is rate limited, but it does not answer the
way rate limiting is normally signalled. There is **no HTTP 429** and **no
`Retry-After` header** — it returns a plain `400 BAD_REQUEST_ERROR` whose
`description` is the string `"Too many requests"`. Code that branches on status
code sees an ordinary bad request, concludes the payload is malformed, and gives
up on an entity that would have succeeded a second later.

**Why it mattered here specifically.** Each of those eighteen amounts was chosen
to probe a particular fee-rounding boundary, and captured payments are now
hand-made and therefore expensive (INCIDENTS.md #10). Silently dropping thirteen
of them would not have produced an obviously broken batch — it would have
produced a *smaller* one, still plausible, missing exactly the calibration points
that distinguish half-up from banker's rounding.

**Fix.** Three parts, and the third is the one that matters.

1. Recognise the limiter by message rather than status code, since the status
   code carries no information.
2. Exponential backoff, 2s doubling to a 30s ceiling. Two amounts needed the
   full ladder before succeeding.
3. **The registry is a checkpoint.** Every minted link is written to
   `results/mint_batch.json` immediately, and a re-run skips any amount already
   present. A partial batch is resumable rather than restarted, which is what
   made recovering the missing thirteen free instead of a re-mint of all
   eighteen.

**The general lesson, and it applies well beyond this script.** Two of the
Razorpay behaviours found on day one — eventually-consistent list endpoints
(#8) and a rate limiter disguised as a 400 (#11) — fail in the same direction:
**they produce a short result set rather than an error.** A harness that trusts
either one builds a candidate pool with holes in it, and the solver then reports
exceptions that are artefacts of the harness while looking like genuine
findings. Both are now handled by reconciling against ids recorded at creation
time and never trusting a collection response to be complete.

---

### #12 — Razorpay's fee is not a percentage, and I can prove it

**Date** 23 Aug · **Landed in** `src/milaan/fees.py` · **Pinned by** `tests/test_fee_model.py`

**What I was testing.** A settlement credit is `Σ(payment − fee) − Σ(refunds)`,
so a cover only closes to the paise if every member's fee is exactly right.
Razorpay publishes a *rate* but no *rounding rule*, and the rounding rule is
what a paise-exact identity turns on. So I minted eighteen payment links at
amounts chosen to probe the boundary — `fee = amount × 11/500`, which lands on
exactly half a paise when `amount ≡ 250 (mod 500)` — and had them paid by hand.

**What came back.**

1. Base rate confirmed: **2.200% of gross**, exact at the four largest amounts.
2. Rounding is **not banker's**. Both half-paise probes rounded *up*:
   ₹7.50 → 17p (banker's predicts 16p), ₹507.50 → 1117p (banker's predicts 1116p).
   That was the question the batch was built to answer, and it is answered.
3. **Ceiling fits 16/18. Half-up fits 13/18.** Ceiling is the model.

**The two that nothing explains.**

```
    251p   exact   5.522   ceil   6   Razorpay charged   7
  10251p   exact 225.522   ceil 226   Razorpay charged 227
```

Both `≡ 251 (mod 500)`, both odd, both one paise **above** ceiling. Their mirror
images just below the boundary — 249p and 10249p, also odd — match ceiling
exactly. All four odd amounts in the batch exceeded half-up; only one of
fourteen even amounts did.

**Why this is not a rounding question.** I tried to rescue it by fitting a
different rate, and it cannot be done. `ceil(r × 10251) = 227` requires
`r > 226/10251 ≈ 0.0220466`. `ceil(r × 500000) = 11000` requires
`r ≤ 11000/500000 = 0.022`. **The intervals are disjoint.** No single percentage,
under any rounding rule, reproduces both observations. There is a discrete
component to Razorpay's fee computation that nineteen samples do not resolve.
That proof ships as a test so a future refactor cannot quietly fit its way out
of it.

**What the system does about it.** `fee_for()` returns a fee *and* a confidence.
An observed fee always beats the model — the model is a fallback for entities
whose fee was never returned, never an override for one that was. An amount in a
residue class known to defeat the model comes back `confident=False` and is
routed to a `FEE_MODEL_RESIDUAL` exception rather than closing a cover.

**Why this is the most useful thing found so far.** Incident #5 said, before any
of this data existed, that the fee model's residual must be *reported as a
number and any remainder made a named exception class, not absorbed*. I wrote
that as a discipline. It turns out to be load-bearing: a model that absorbed
these two would produce a cover that is off by exactly one paise, and a
one-paisa error does not look wrong — it turns a correct match into an
unexplained exception, or worse, lets a wrong subset close. Two payments out of
nineteen, roughly 11%, would have been silently mis-modelled.

**Also found:** `tax` is 0 on sixteen of nineteen payments and 18% on the two
largest only. The threshold sits between ₹999 and ₹2,499 and is undocumented, so
the GST line is only partially exercised in test mode. `LIMITS.md` says so
rather than the results table implying otherwise.

**Open question, honestly open.** Whether the anomaly is parity, the residue
class, or something else entirely needs a targeted follow-up batch — odd/even
pairs bracketing the boundary at several magnitudes. Until then it is reported
as unexplained, because it is.

---

### #13 — test mode caps payment links at 30, and that retroactively justifies the whole data plan

**Date** 23 Aug · **Found by** `scripts/mint_followup.py` on its eighth link

**Symptom.** The follow-up probe batch minted seven links and then stopped:

```
RATE_LIMIT_EXCEEDED · "test mode limit of 30 reached for payment_link"
```

**Cause.** Razorpay test mode enforces a **hard ceiling of 30 payment links per
account**. Not a throttle — a cap. Twenty-nine had been created across the day's
probes and two calibration batches, and the thirtieth was refused.

**Note the contrast with #11.** That earlier limiter returned a plain
`400 BAD_REQUEST_ERROR` whose description was `"Too many requests"` — no code, no
`Retry-After`, indistinguishable from a malformed payload. This one returns a
proper `RATE_LIMIT_EXCEEDED` with a message that names the resource and the
number. Razorpay therefore has **two different rate-limiting behaviours on the
same endpoint**, and only one of them is machine-readable. A harness that handled
either one alone would misread the other: backing off forever against a hard cap,
or giving up immediately against a soft throttle.

**Why this is the most strategically useful finding of the day.** MILAAN's ground
truth was already the sealed, seeded, hash-committed generator, with live
Razorpay data positioned as a *second* results column if it ever materialised.
That call was made on 21 August, before any of this was known.

It now turns out that **three independent hard limits** would each, on their own,
have made a large live-minted pool impossible:

1. `GET /v1/settlements` is empty on an unactivated account, so Razorpay-authored
   groupings do not exist to be harvested (probe E4).
2. Checkout runs hCaptcha, so payments cannot be captured programmatically (#10).
3. Payment links are capped at 30 per test account — this entry.

A plan that had made "mint 300 real payments and let Razorpay's engine author the
answer key" the spine would have discovered limit 3 somewhere around day six,
with the solver already built against an assumption that could not hold. The
sealed generator was not a fallback taken under duress; it was the primary
choice, and each of these findings is a separate reason it was the right one.

**What it costs.** The 30-link budget is now spent, so the fee-model corpus is
frozen at 19 measured payments plus the 7 probes in flight — 26 total. That is
enough to answer the rounding question and to map the anomaly's fractional
neighbourhood, and it is not enough to characterise the discrete component fully.
`LIMITS.md` states the sample size and stops there.

---

### #12b — the anomaly, localised

**Date** 23 Aug · **Resolves the open question in #12** · **Pinned by** `tests/test_fee_model.py`

#12 left the question open and said so. A second batch of seven links answered
it: sweep the fractional part of the exact fee at constant magnitude, with
controls, and find where the +1 lives.

Writing `k = (amount × 11) mod 500`, so the exact fee is `q + k/500`, across all
25 measured payments:

```
 frac   .478  .500  .502 │ .510  .522  .540 │ .560  .600  .700  .900
 delta   +0    +0    +0  │  +1    +1    +1  │  +0    +0    +0    +0
 n       2     5     1   │  1     2     1   │  1     2     1     1
                         └──── the band ────┘
```

The band is `(0.502, 0.560)`, bracketed to within 0.008 on the left and 0.020 on
the right. Every amount inside came back at ceiling + 1; every amount outside
matched ceiling exactly.

**The controls did their job.** Three probes at .600, .700 and .900 were minted
expecting +0 precisely so that a backend change affecting everything would be
distinguishable from a real effect. They came back +0. The effect is real.

**And the stronger claim now holds over the full dataset.** Intersecting the
feasible rate interval implied by each of the 25 observations gives the **empty
set** — under ceiling and under half-up alike — and allowing an additive constant
does not rescue it either. Razorpay's test-mode card fee is **not expressible as
any single percentage of gross**. Both proofs ship as tests rather than as prose,
so a later refactor cannot fit its way out of them.

**What ships.** Two models, both reported. `base_fee_ceiling` is conservative and
fits 21/25. `base_fee_banded` adds the measured +1 inside the band and fits
25/25 — *by construction*, which is exactly why the evaluation publishes the
match rate under both. A curve fitted to four points is a hypothesis, not a
result, and presenting the 25/25 alone would be the kind of flattering number
this project exists to avoid.

Amounts inside the band still come back `confident=False` and route to
`FEE_MODEL_RESIDUAL`.

**What is still unknown, and stays unknown.** *Why* the band exists. The 30-link
test-mode cap (#13) is now spent, so the corpus is frozen at 25. Narrowing
`(0.502, 0.560)` further, or explaining the discrete component behind it, needs
an account this project does not have. `LIMITS.md` states the sample size and
stops there.

---

### #14 — the solver called a provably ambiguous problem UNIQUE

**Date** 23 Aug · **Found by** an external audit of this repo · **Pinned by** `test_a_zero_valued_candidate_makes_every_cover_ambiguous`

**Symptom.** `solve([100, 0], 100)` returned `UNIQUE` with cover `(0,)`. Brute
force finds **two** covers: `{0}` and `{0, 1}`. Same for `solve([0], 0)` (two
covers) and `solve([100, 0, 0], 100)` (four).

**Cause.** A zero-valued entry can join or leave any cover without changing its
sum, so `k` zeros give every solution `2^k` equivalent variants. The bitset DP
cannot see this: shifting by zero is the identity, so `reachable | (reachable << 0)`
is a no-op, a zero-weight item is never selected during reconstruction, and
`_find_second` only ever pins out members of the first solution — so an item
that is absent from that solution is never tried. The solver returned the single
cover that omits every zero and called it unique.

**Why this is the worst bug in the project so far.** It falsifies the headline
guarantee. MILAAN's entire claim is that `UNIQUE` means *no second cover exists*
— that is the difference between a reconciliation engine and a suggestion
engine, and it is the sentence the pitch is built on. For a whole class of
inputs it was simply false.

And it was reachable from real data, not a contrived fixture: `LedgerEntry.net`
returns exactly `Paisa(0)` for any row where `debit == credit`, which a fee-only
adjustment or a fully-refunded payment produces.

**Why 100+ passing property tests missed it.** Every random generator I wrote
starts at `rng.randint(1, ...)`. **A zero was never sampled — not once, in any
test, in the entire suite.** The brute-force oracle was correct and would have
caught this immediately; it was never handed an input that could expose it. The
oracle was right and the corpus was blind, which is a more uncomfortable failure
than a wrong oracle: every green run was evidence about a region of the input
space I had silently excluded.

**Fix.** Zero-valued candidates are partitioned out before the DP. If any exist
and a cover exists, the verdict is `AMBIGUOUS` with both witnesses — the cover
with and without a zero. `test_property_tests_now_generate_zeros` asserts the
generator actually produces zeros, so the corpus itself is now under test rather
than only the solver.

**What I take from it.** A property test is only as good as its generator, and
"all tests pass" is a statement about the corpus as much as the code. The
generator is now an artifact I review, not scaffolding I write once.

---

### #15 — `fee` meant two different things and the difference was exactly the GST

**Date** 23 Aug · **Found by** an external audit of this repo · **Pinned by** `test_observed_and_modelled_fees_agree_on_what_net_means`

**Symptom.** `FeeEstimate.fee_paise` was **tax-inclusive** when it came from
Razorpay's API and **tax-exclusive** when it came from the model. One ₹2,499
payment produced three different answers for its net:

```
observed  fee_paise=6488 tax_paise=990  ->  amount-fee-tax = 242422   (wrong, double-counts GST)
modelled  fee_paise=5498 tax_paise=0    ->  amount-fee-tax = 244402   (wrong, no GST at all)
truth     Razorpay charged 6488 all-in  ->  net             243412
```

**Cause.** Razorpay reports `fee` **inclusive** of `tax`, while the 2.200% rate
applies to the base. I knew this — `tests/test_fee_model.py` defines
`_base(fee, tax) = fee - tax` with that exact comment, and
`scripts/mint_followup.py` does the same subtraction. The knowledge simply never
made it into `fees.py`, so the two paths disagreed about what a single field
name meant.

**Why 990 paise matters here more than it sounds.** A cover either closes
exactly or it does not. An off-by-990p member does not produce a slightly wrong
total — it turns a correct match into an unexplained exception, or lets a wrong
subset close. This is precisely the silent financial misstatement the README's
second paragraph is about, sitting in the module that computes money.

**Fix.** The ambiguity is now unrepresentable. There is no field called `fee`:
`base_fee_paise` is tax-exclusive on every path, `tax_paise` is the GST on it,
`gross_fee_paise` is the all-in figure Razorpay reports, and
`net_settled_paise` is the only number a cover is ever built from. A test asserts
all four agree across every one of the 25 measured payments.

**The pattern across #14 and #15.** Both were found by someone else reading the
code, not by me writing more of it — and both were in modules I had already
covered with tests I trusted. #14 was a blind spot in my generator; #15 was
knowledge that lived in a test helper and a script but never reached the module
that needed it. Neither was a hard bug. Both were invisible from the inside.
