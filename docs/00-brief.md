# Razorpay AI Buildathon — Official Brief (captured verbatim 2026-08-21)

Source: https://razorpay.com/buildathon/ · Form: https://forms.gle/d9r2gvxp8cmoZhon9
**Applications close 5 September 2026.** Today: 21 August 2026 → ~15 days.

## The offer
- ₹75,000/month stipend · 6 or 12 months (your pick) · In-person, Bangalore, from September
- Shortlisted builders go straight to a panel. No aptitude test. No group discussion.

## How they judge — "We read the work, not the resume."
| Criterion | Definition (verbatim) |
|---|---|
| **Problem taste** | did you pick something that actually matters |
| **Build quality** | does it run, is it structured, would you trust it |
| **AI judgment** | the right tool in the right place, **and where you chose not to use one** |
| **Failure recovery** | what broke, and what you did about it |

## The form asks for exactly 12 things
About you: Full name · College · Graduation year · In-person from September (y/n) · 6 or 12 months · Resume file
About the build: **Track** · **Project name** · **What it solves** · **GitHub repo URL (public)** · **5-min pitch video (unlisted ok)** · **What broke, and how you got out**

> "We still take the resume. We just don't screen on it. **The last one is the one we read first.**"

⇒ The "what broke" answer is the highest-leverage field on the form.

---

## The five tracks (verbatim)

### 01 — AI Growth & Agentic Commerce
> Grow the merchant's revenue, and make them sellable to AI buyers.
> Build an agent that grows revenue for a merchant on Razorpay test-mode APIs, or that makes a merchant transactable by an AI buyer end to end.
> **Why now:** NPCI's UAP and the global protocol race (ACP, AP2, x402) make agent-to-agent commerce the open problem of the year, and Razorpay's in-app pilots are already live.
> **Example directions:** Conversational in-app checkout · Agent-readable catalog · Upsell & cross-sell agent · Campaign orchestrator
> **The bar:** Every money action explainable, bounded and gated. Show the audit trail and one failure handled gracefully.

### 02 — AI Risk Manager
> Stop the merchant losing money to fraud, returns and chargebacks.
> Build a working detector, verifier or auto-responder for one class of loss, with measured precision and recall on a held-out test set.
> **Why now:** AI-enabled fraud is hitting Indian BFSI while returns and chargebacks quietly eat margin. This track surfaces the risk and ML minded builders the others miss.
> **Example directions:** Chargeback evidence responder · Return-risk scorer · Fraud-spike detector · Abuse-ring sentinel
> **The bar:** Honest metrics including false-positive cost. Strictly defense-only: anything offense-capable is disqualified.

### 03 — AI Revenue Recovery
> Find revenue that's slipping away and win it back.
> Build an agent that detects revenue at risk, determines the right intervention, and executes a bounded recovery workflow: from payment failures and checkout abandonment to overdue receivables.
> **Why now:** Revenue loss rarely happens in one clean step. A payment degrades, a checkout gets abandoned, a subscription fails, or an invoice goes overdue. AI can now close the loop from detecting the problem to diagnosing it, choosing the right intervention, and recovering the money.
> **Example directions:** Payment degradation → root cause → recovery action · Checkout drop-off recovery · Failed-subscription recovery · B2B receivables chaser · Mandate retry sequencer · Hinglish voice recovery · Promise-to-pay tracker
> **The bar:** Don't just identify the problem. Show **measured money recovered across a batch**, with compliant escalation, stopping rules, and an audit trail.

### 04 — AI Finance Controller
> Run the books and the cash position.
> Build an agent that closes one finance-ops loop across a **50+ record batch of synthetic data**, reporting its match rate and the exceptions it could not resolve.
> **Why now:** The 2026 builder consensus: verification capacity, not generation speed, is the bottleneck. Reconciliation, settlement and forecasting are still done by hand.
> **Example directions:** Multi-source reconciliation · Settlement Q&A agent · Forward cash forecaster · Tax-line matcher
> **The bar:** Throughput plus measured accuracy plus an honest exception list. One cherry-picked match proves nothing.

### 05 — Open Track
> Build what you believe should exist.
> Have an idea that doesn't fit the tracks above? Build it. Pick a real problem, use AI meaningfully, and show us something that works. Any domain, workflow, or user is fair game.
> **Why now:** The best ideas don't always fit a predefined category. This track exists for builders who see an opportunity we didn't.
> **Example directions:** Surprise us · Solve a problem you deeply understand · Build something we haven't thought of
> **The bar:** Open doesn't mean easier. Show a real problem, a working product, meaningful use of AI, and evidence that it creates value. The same bar for execution, reliability, and depth applies here.
