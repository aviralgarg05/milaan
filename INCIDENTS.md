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
