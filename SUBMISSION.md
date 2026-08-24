# Submission — ready to paste

Razorpay AI Buildathon 2026 · Form: https://forms.gle/d9r2gvxp8cmoZhon9

| Field | Value |
|---|---|
| **Selected Track** | 04 — AI Finance Controller |
| **Project Name** | MILAAN |
| **GitHub Repository URL** | https://github.com/aviralgarg05/milaan |
| **5-min Pitch Video Link** | *(record from the script below)* |

---

## Project Objectives — "What does it solve?"

A merchant's bank statement shows one credit: `₹8,36,833.41`, narration
`NEFT-HDFC0000123-RAZORPAY SOFTWARE-N2938471`. Razorpay's dashboard shows 340
individual payments, some refunds, and a per-transaction fee. Which transactions
make up that credit?

Today this is done by hand, or not at all. It matters because that join is how a
merchant knows they were paid what they were owed — and because a **wrong** join
is worse than no join. A wrong join produces a reconciliation report that
balances, so nothing downstream ever catches it. It is a silent financial
misstatement.

MILAAN reconstructs the composition of a bank credit to the paise, and **refuses
rather than guesses** when more than one answer fits. On a sealed 18-credit,
237-row batch it recovers the grouping on **80% of decidable credits**,
correctly refuses **3 of 3** structurally-undecidable ones, and reports **zero
wrong joins** — at 79 credits/second.

That last number is the one that matters. A match rate can be raised by
guessing; a false-match count cannot.

Two things make it a Razorpay project specifically rather than generic fuzzy
matching. First, **Razorpay does not have the merchant's bank statement** — all
eight Agent Studio agents operate on data already inside Razorpay, and Settlement
Insights pushes their view outward without ever reading the bank's view back in.
This is the seam between the two. Second, the fee model is **measured, not
assumed**: 25 real captured test-mode payments established that Razorpay charges
2% and 0.2% *rounded up separately*, not one 2.2% rate — a one-paisa difference
on 4 of 25 payments, which is exactly the error that turns a valid cover into an
unexplained exception.

The agent is a real policy loop, not a pipeline with a label: a fixed candidate
window is genuinely wrong (too wide invites ties, too narrow excludes members —
opposite failures), so it chooses the window by reacting to how the last attempt
failed, across ~6.7 bounded, replayable decisions per credit.

Where an LLM is used is deliberately narrow, and its contribution is **measured
rather than claimed**: a *perfect* extractor is offered **zero** lines on this
batch — the agent's policy resolves everything either by structure or by an
honest refusal before the one branch where a hint could act is ever reached —
and its ceiling is **+0** regardless. That zero, and the reachability count
behind it, are published rather than engineered to look more impressive
(INCIDENTS.md #25 is the near-miss where I almost shipped the "4 lines" version
of this sentence before verifying it).

---

## Build Challenges & Technical Obstacles — "What broke, and how you got out"

*(the field Razorpay says they read first)*

27 entries in `INCIDENTS.md`, written as they happened with commit hashes and
the regression test that pins each. **Eight of them are cases where the thing
that broke was my own conclusion rather than my code.** Those are the ones
worth your time.

**The solver said UNIQUE on a provably ambiguous input.** `solve([100, 0], 100)`
returned a single cover when brute force finds two — a zero-valued entry joins or
leaves any cover freely, and shifting a bitset by zero is the identity, so the DP
never selected one. This falsified the guarantee the whole project rests on, and
it was reachable from real data: a ledger row nets to exactly zero whenever debit
equals credit. **Over a hundred property tests missed it because every random
generator I wrote starts at `randint(1, …)` — a zero was never sampled once in
the entire suite.** The oracle was correct; the corpus was blind. There is now a
test asserting the generator produces zeros, so the corpus itself is under test
and not just the code.

**The first end-to-end run scored 0.0%, and the solver was right every time.** I
had built the interesting algorithm first — signed subset-sum, uniqueness proof,
bitset DP — and called it the product. On a ±6-day pool of ~200 candidates there
are 2²⁰⁰ subsets against ~10⁷ achievable sums, so by pigeonhole almost every
target has many exact covers. Ambiguity wasn't an edge case; it was guaranteed,
and an engine reporting a single cover anyway would have been guessing. The cheap
layers I'd listed in the README as "optimisations" are what makes the problem
decidable at all. Adding the interval layer took it 0% → 75%; **false matches
were zero before and after**, which is the point — structure didn't make the
engine willing to guess, it made the questions decidable.

**I proved a negative and stopped one question short.** Twenty-five real test
payments showed four fees sitting one paise above `ceil(2.2%)`. I localised the
effect to a fractional band, proved rigorously that *no single percentage under
any rounding rule* fits all 25, published it as unexplained, and shipped two
models side by side. An external review of the repo found it in one line:
`ceil(a/50) + ceil(a/500)`. Two components rounded up separately — 25 of 25,
including all four. My impossibility proof was correct and pointing straight at
the answer; I had asked *which rate is it* and never *is it one rate*. I kept the
original entries as written rather than rewriting them to look like I'd found it.

**I diagnosed before building, once, and it saved a day.** Three of four
refund-bearing credits were refused, and the plan said build a perturbed-interval
layer. Ten minutes checking *why* showed the true member sets weren't contiguous
at all — I was sorting by id, and `pay_` sorts before `rfnd_`, so one
settlement's refunds landed after the next settlement's payments. Perturbation
would have made it worse, since it adds candidate covers. The real fix was a
domain fact: ledger rows carry a capture timestamp, and settlement follows it.
80% decidable, refunds 1/4 → 4/4.

**I took a lower number on purpose.** A credit I'd planted as `AMBIGUOUS_COVER`
came back matched — correctly, because it covered *all seven* identical payments
and "all of them" is a unique set. My generator planted a *condition* and I'd
named the class after an *outcome*, so a right answer scored as a failure and,
worse, three genuine failures were being excused as "correctly refused". Fixing
the denominator dropped the headline from 91.7% to **80.0%**. A denominator that
excuses whatever the engine failed at is not a measurement.

**An audit said this wasn't an agent, and it was right.** A fixed ±6-day
candidate window is a genuine defect, not a stylistic gap: too wide invites
ties (honest `AMBIGUOUS`), too narrow excludes members (honest `NO_COVER`) —
opposite failures a constant cannot resolve but a feedback loop can. I built
`ReconciliationAgent`: a deterministic policy over a bounded window ladder
(1/2/3/4/6 days) that widens on `NO_COVER`, narrows on `AMBIGUOUS`, stops on
`UNIQUE`, fully replayable with `milaan run --trace`. **It produced a false
match within the hour of existing** — accepting "unique" at a narrow window
without checking whether a wider one hid a second cover, the exact
manufacture-uniqueness failure `hints/grounding.py` was built to forbid,
recommitted in a different module while fixing the thing that forbids it.
Fixed by deciding on the widest evidence available, not the first window that
looks clean, before ever accepting.

**The AI layer was never reachable, then reachable but wrong, then wasteful.**
Asking "is the AI thing actually done?" and testing rather than trusting the
answer found three separate defects stacked on each other. First: `milaan run`
had no flag to request a live model at all — `AnthropicProposer` had zero test
coverage and was reachable only from a Python shell, never from any documented
command. Second, once I added `--live-hints`: it crashed immediately,
`AttributeError: no attribute 'hint_for'` — the real proposer implements
`propose()`, its only caller calls `hint_for()`, and nobody had ever run the
two against each other. A valid API key would have hit the identical crash.
Third, once fixed: a fake-key run showed 9 calls, 9 errors, when only 2 of 18
episodes can ever reach the branch that uses a hint — a 4.5× overspend built
in by computing the hint eagerly instead of lazily. Fixed by making the hint a
zero-argument callable invoked at most once, only from the one branch that can
use it. Re-measured: exactly 1 call, matching the one credit that both needs
one and can use it.

**Two things I refused to do.** Razorpay's checkout runs hCaptcha, which killed
automated payment minting — I did not try to defeat it, because a data pipeline
that depends on evading a payment provider's fraud controls is not one you want
to explain to that payment provider. And the LLM layer's measured contribution is
**+0**: once the interval layer resolves 16 of 18 credits, the hint layer is
offered zero lines. Containment predicts it would still be +0 if invoked —
uniqueness is adjudicated on the full pool, so a hint cannot break a tie — but
that is an architectural argument backed by the adversarial config, not something
this particular run demonstrated. The only route to a positive number is
weakening containment, which buys it with the wrong joins this project exists to
prevent. So the zero is published, with its cause stated accurately.

Along the way: Razorpay's list endpoints are eventually consistent, and its rate
limiter returns a plain `400` reading "Too many requests" rather than a 429.
Both fail in the same direction — they return a *short result set* rather than an
error — which would have silently built a candidate pool with holes in it and
produced exceptions that looked like real findings.

---

## 5-minute video script

**0:00–0:25 · The problem, in their own data.** Terminal, `pytest` running.
"This is Razorpay's own published sample settlement report. Three settlements.
Each one's members sum to its total exactly, in integer paise — including this
one, five payments minus a refund, 395 paise. The fourth doesn't close, and
that's not a bug in their data: it's an out-of-window settlement. My exception
taxonomy was validated against someone else's data before I wrote a solver."

**0:25–1:10 · Why this is hard, and why a wrong answer is worse than none.**
"A merchant's bank statement shows one lump credit. Razorpay's dashboard shows
340 transactions. Nobody joins them. And a wrong join is worse than no join —
it produces a report that balances, so nothing downstream catches it. That's why
the number I lead with isn't the match rate."

**1:10–1:45 · `milaan run --trace`.** Live. Scorecard first, then one credit's
trace. "Eighteen credits, 237 ledger rows. 80% on decidable credits, zero false
matches. But look at how it gets there —" *(point at one trace line)* "— that's
not a script, it's a loop: try a window, widen if nothing sums, narrow if too
much does, stop when one answer survives. Every decision, replayable."

**1:45–2:25 · Why the loop exists, and what it did to me.** "A fixed window is
provably wrong — too wide invites ties, too narrow excludes members, opposite
failures. So I built a policy that reacts instead. It reported a false match
within the hour: accepting the first window that looked unique, when a wider one
hid a second answer. That's the exact thing I'd already forbidden a hint from
doing three files away, and I did it anyway building the next layer. Fixed the
same way — decide on the widest evidence, not the first."

**2:25–3:00 · The refusal, on screen.** Show an `AMBIGUOUS_COVER` with both
witnesses. "Two different subsets sum to this credit exactly. I can't tell you
which one is real, so I don't. Here are both. Subscription merchant, identical
prices — the common case, not an edge case."

**3:00–3:50 · Where the LLM is, and the number I didn't want.** Run
`milaan hints`. "Ceiling on any model: **plus zero**. Uniqueness is decided on
the full pool, so a hint can never break a tie — the property that makes it
safe is what makes it useless here. And when I wired in a real API call, it
crashed — wrong interface, then discovered it was about to make nine paid calls
for two credits that could ever use one. Fixed both. `--live-hints` now makes
exactly one call, on exactly the credit that needs it, and degrades cleanly
when the key is bad. I could get a positive ceiling by weakening containment.
It would be bought with wrong joins."

**3:50–4:30 · What broke.** "Twenty-seven incidents. Eight are my own words or
conclusions being the defect, not my code. A hundred property tests missed a
solver bug because no generator I wrote ever sampled a zero. My first run
scored 0% and the solver was right every time. I proved no single rate fit
Razorpay's fee and stopped one question short — someone else found the real
answer in one line. And I lowered my own headline, 91.7% to 80%, because the
higher number was excusing failures in its own denominator."

**4:30–5:00 · Limits.** "Eighteen credits, one seed. The grouping rule is my
reading of Razorpay's T+2 cycle, not an observation of it. The narrations are
synthetic. The fee model isn't — that's 25 real charges from their engine, and
the agent's window policy is real code making real decisions, not a label. What
I can defend is narrow and exact: given a ledger and credits grouped by a
documented rule, it recovers the grouping 80% of the time and never once
reported a join that wasn't real."

**Recording notes.** One take for `milaan run --trace` and `milaan hints` —
both finish in under a second; `--live-hints` with a bad key adds about a
second for the real HTTP round trip. Don't re-enact the ambiguous-cover moment
or the agent's false-match story; both are stronger said plainly than acted
out. Read the limits slide slower than feels natural.
