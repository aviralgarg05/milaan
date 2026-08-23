#!/usr/bin/env python3
"""Generate a calibration batch of payment links, and a page to work through them.

Headless minting is RED (INCIDENTS.md #10) — Razorpay's checkout runs hCaptcha
and defeating it is out of bounds. So captured payments are produced by hand,
which makes each one expensive and means the amounts have to be *chosen* rather
than sampled.

They are chosen to pin the fee model. The observed rate is 2.200%, i.e.

    fee = amount × 11/500

whose fractional part is `(amount × 11 mod 500) / 500`. That lands on exactly
0.5 paise when `amount ≡ 250 (mod 500)` — so ₹2.50, ₹7.50, ₹12.50, ₹102.50 and
₹507.50 are the amounts that distinguish **half-up** rounding from **banker's
rounding**, which no published pricing page states and which a settlement either
closes on or does not. Their immediate neighbours (±1 paisa) bracket the
boundary from both sides.

The rest spread across magnitudes, including ₹1 — the smallest legal amount,
where 2.2% is 2.2 paise and where Razorpay's own sample shows an all-in fee of
1p with tax 0.

Writes `results/mint_batch.json` as the entity registry. That registry is the
fix for INCIDENTS.md #8: collection endpoints are eventually consistent, so the
ledger is reconciled against ids recorded at creation time, never discovered by
listing.

    uv run scripts/mint_links.py          # create the batch + open the page
    uv run scripts/mint_links.py --check  # reconcile what has been paid so far
"""

from __future__ import annotations

import base64
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "results" / "mint_batch.json"
PAGE = ROOT / "results" / "mint_batch.html"
RATE_NUM, RATE_DEN = 11, 500  # 2.200%, as observed on pay_TTGbjjcwSCSQaC
THROTTLE_SECONDS = 3.0  # POST /payment_links is rate limited; see INCIDENTS.md #11

# (paise, why this amount is in the batch)
AMOUNTS: list[tuple[int, str]] = [
    (100, "smallest legal amount; 2.2% = 2.2p. Razorpay's sample shows fee=1p tax=0"),
    (249, "one paisa below a .5 fee boundary"),
    (250, "fee = 5.5p exactly — half-up vs banker's rounding"),
    (251, "one paisa above a .5 fee boundary"),
    (750, "fee = 16.5p exactly — second rounding probe"),
    (1250, "fee = 27.5p exactly — third rounding probe"),
    (4900, "₹49, ordinary small ticket"),
    (9900, "₹99 — the amount in Razorpay's own sample report"),
    (10249, "below a .5 boundary at a larger magnitude"),
    (10250, "fee = 225.5p exactly — rounding probe at ₹102.50"),
    (10251, "above a .5 boundary at a larger magnitude"),
    (29900, "₹299, common subscription price"),
    (49900, "₹499 — matches the already-captured pay_TTGbjjcwSCSQaC"),
    (50750, "fee = 1116.5p exactly — rounding probe at ₹507.50"),
    (71300, "₹713, arbitrary non-round mid ticket"),
    (99900, "₹999, common D2C price point"),
    (249900, "₹2,499, larger ticket"),
    (500000, "₹5,000, top of the calibration range"),
]


def creds() -> str:
    env: dict[str, str] = {}
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip().strip("'\"")
    key = env.get("RAZORPAY_KEY_ID")
    sec = env.get("RAZORPAY_KEY_SECRET")
    if not key or not sec:
        sys.exit("no credentials in .env — see .env.example")
    if key.startswith("rzp_live_"):
        sys.exit("REFUSING: that is a live key.")
    return base64.b64encode(f"{key}:{sec}".encode()).decode()


def api(auth: str, method: str, path: str, payload: dict | None = None):
    data = json.dumps(payload).encode() if payload else None
    req = urllib.request.Request(
        f"https://api.razorpay.com/v1{path}", data=data, method=method,
        headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode() or "{}")


def predicted_fee(amount: int) -> tuple[int, int, str]:
    """Half-up and banker's predictions, and whether this amount distinguishes them."""
    num = amount * RATE_NUM
    half_up = (num * 2 + RATE_DEN) // (2 * RATE_DEN)
    q, r = divmod(num, RATE_DEN)
    if r * 2 == RATE_DEN:  # exact .5 — the interesting case
        bankers = q if q % 2 == 0 else q + 1
    else:
        bankers = half_up
    return half_up, bankers, "DISTINGUISHES" if half_up != bankers else ""


def create_link(auth: str, amount: int, *, attempts: int = 6) -> dict | None:
    """Create one payment link, backing off through Razorpay's rate limiter.

    `POST /payment_links` is rate limited and answers with a plain
    `BAD_REQUEST_ERROR / "Too many requests"` — no 429, no `Retry-After` header,
    so the caller has to recognise it by message and choose its own delay.
    See INCIDENTS.md #11.
    """
    delay = 2.0
    for attempt in range(attempts):
        status, body = api(auth, "POST", "/payment_links", {
            "amount": amount, "currency": "INR",
            "description": f"MILAAN calibration {amount}p",
            "customer": {"name": "MILAAN calibration",
                         "email": "calibration@example.invalid",
                         "contact": "+919000090000"},
            "notify": {"sms": False, "email": False},
            "reminder_enable": False,
            "notes": {"trace": "milaan-calibration", "amount_paise": str(amount)},
        })
        if status == 200:
            return body
        message = json.dumps(body)
        if "Too many requests" not in message:
            print(f"  ✗ {amount:>7}p  {message[:110]}")
            return None
        if attempt < attempts - 1:
            print(f"    {amount:>7}p rate limited, retrying in {delay:.0f}s")
            time.sleep(delay)
            delay = min(delay * 2, 30)
    print(f"  ✗ {amount:>7}p  still rate limited after {attempts} attempts")
    return None


def mint() -> None:
    auth = creds()

    # Resume: never re-mint an amount that already has a link. A partial batch is
    # a checkpoint, not a failure, and re-running must be free.
    existing: dict[int, dict] = {}
    if REGISTRY.exists():
        for row in json.loads(REGISTRY.read_text()).get("links", []):
            existing[row["amount_paise"]] = row
    if existing:
        print(f"resuming: {len(existing)} links already minted")

    rows: list[dict] = []
    todo = [(a, w) for a, w in AMOUNTS if a not in existing]
    print(f"minting {len(todo)} payment links (throttled)\n")

    for amount, why in AMOUNTS:
        if amount in existing:
            rows.append(existing[amount])
            continue
        link = create_link(auth, amount)
        if link is None:
            continue
        hu, bk, flag = predicted_fee(amount)
        rows.append({"amount_paise": amount, "why": why, "payment_link_id": link["id"],
                     "short_url": link["short_url"], "predicted_fee_half_up": hu,
                     "predicted_fee_bankers": bk, "distinguishes_rounding": bool(flag)})
        print(f"  ✓ {amount:>7}p  {link['short_url']:<32} fee≈{hu}p {flag}")
        time.sleep(THROTTLE_SECONDS)

    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY.write_text(json.dumps({
        "created_at": datetime.now(timezone.utc).isoformat(),
        "purpose": "fee-model calibration; amounts chosen to pin the rounding rule",
        "observed_rate": "2.200% (fee = amount * 11/500), from pay_TTGbjjcwSCSQaC",
        "links": rows,
    }, indent=2))
    _write_page(rows)
    n = sum(r["distinguishes_rounding"] for r in rows)
    print(f"\n{len(rows)} links · {n} of them distinguish half-up from banker's rounding")
    print(f"registry  {REGISTRY.relative_to(ROOT)}")
    print(f"open      {PAGE.relative_to(ROOT)}")


def _write_page(rows: list[dict]) -> None:
    items = "\n".join(
        f'<li><a href="{r["short_url"]}" target="_blank" rel="noopener">'
        f'<b>₹{r["amount_paise"]/100:,.2f}</b></a>'
        f'<span class="{"k" if r["distinguishes_rounding"] else ""}">'
        f'{"rounding probe · " if r["distinguishes_rounding"] else ""}{r["why"]}</span></li>'
        for r in rows
    )
    PAGE.write_text(f"""<!doctype html><meta charset=utf-8>
<title>MILAAN · calibration batch</title>
<style>
 body{{font:15px/1.5 ui-sans-serif,system-ui;max-width:820px;margin:3rem auto;padding:0 1rem;color:#111}}
 li{{margin:.5rem 0;display:flex;gap:.75rem;align-items:baseline}}
 a{{min-width:6.5rem;text-align:right;font-variant-numeric:tabular-nums}}
 span{{color:#666;font-size:13px}} .k{{color:#b45309;font-weight:600}}
 code{{background:#f4f4f5;padding:.1rem .3rem;border-radius:3px}}
 @media(prefers-color-scheme:dark){{body{{background:#0b0b0c;color:#e7e7e9}}
  span{{color:#9b9ba1}} .k{{color:#fbbf24}} code{{background:#1c1c1f}}}}
</style>
<h1>MILAAN calibration batch</h1>
<p>Test mode. No real money moves. Pay each with Visa <code>4100 2800 0000 1007</code>,
any future expiry, any CVV, OTP any 4–10 digits.</p>
<p>The <b>rounding probes</b> matter most — those amounts make the fee land on
exactly half a paise, which is what distinguishes half-up from banker's rounding.
Do those first if you stop early.</p>
<ol>{items}</ol>
<p>When done: <code>uv run scripts/mint_links.py --check</code></p>
""")


def check() -> None:
    auth = creds()
    if not REGISTRY.exists():
        sys.exit("no registry — run without --check first")
    reg = json.loads(REGISTRY.read_text())

    status, payments = api(auth, "GET", "/payments?count=100")
    by_amount: dict[int, list[dict]] = {}
    for p in payments.get("items", []):
        if p.get("status") == "captured":
            by_amount.setdefault(p["amount"], []).append(p)

    print(f"{'amount':>9} {'fee':>7} {'tax':>5} {'half-up':>8} {'bankers':>8}  verdict")
    print("─" * 62)
    paid = agree_hu = agree_bk = 0
    for row in reg["links"]:
        amt = row["amount_paise"]
        hits = by_amount.get(amt)
        if not hits:
            print(f"{amt:>9} {'—':>7} {'—':>5} {row['predicted_fee_half_up']:>8}"
                  f" {row['predicted_fee_bankers']:>8}  unpaid")
            continue
        paid += 1
        fee, tax = hits[0].get("fee"), hits[0].get("tax")
        hu, bk = row["predicted_fee_half_up"], row["predicted_fee_bankers"]
        agree_hu += fee == hu
        agree_bk += fee == bk
        mark = "✓" if fee in (hu, bk) else "✗ MISMATCH"
        if row["distinguishes_rounding"] and fee is not None:
            mark += "  ← half-up" if fee == hu else ("  ← banker's" if fee == bk else "")
        print(f"{amt:>9} {str(fee):>7} {str(tax):>5} {hu:>8} {bk:>8}  {mark}")

    print("─" * 62)
    print(f"{paid}/{len(reg['links'])} captured · "
          f"half-up matches {agree_hu}, banker's matches {agree_bk}")
    if paid:
        print("\nThis table is the fee model's validation against Razorpay's own engine.")
        print("Any MISMATCH is a real finding and becomes a named exception class.")


if __name__ == "__main__":
    check() if "--check" in sys.argv else mint()
