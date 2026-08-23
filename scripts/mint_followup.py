#!/usr/bin/env python3
"""Follow-up batch: map the fractional part where Razorpay's fee exceeds ceiling.

Incident #12 left one thing unresolved. Two amounts — 251p and 10251p — came back
a paise ABOVE `ceil(amount × 11/500)`, while sixteen others matched ceiling
exactly. The first batch could not separate the competing explanations.

**Parity is already ruled out by the data we have.** 249p and 10249p are both odd
and both match ceiling exactly, so "odd amounts get +1" is false.

What is left is the *fractional part*. Writing `k = (amount × 11) mod 500`, the
exact fee is `q + k/500`. Across the first batch:

    k/500 = .478 → +0      .500 → +0      .522 → **+1**
            .600 → +0      .800 → +0      .000 → +0

Only .522 misbehaved, and it is the only sample in `(0.5, 0.6)`. So this batch
sweeps that gap and beyond, holding magnitude roughly constant (~₹100–₹205) so
amount size cannot confound the result.

Since `11 × 91 ≡ 1 (mod 500)`, an amount with `amount ≡ 91k (mod 500)` has
fractional part exactly `k/500`. That is how each probe below was chosen.

Two controls are included deliberately: `.600` should reproduce +0 (71300p did),
and 20251p replicates the known +1 at a third magnitude. A batch with no controls
cannot tell a real effect from a changed backend.

    uv run scripts/mint_followup.py
    uv run scripts/mint_followup.py --check
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from decimal import ROUND_CEILING, Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mint_links import THROTTLE_SECONDS, api, create_link, creds  # noqa: E402

import time  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "results" / "followup_batch.json"
PAGE = ROOT / "results" / "followup_batch.html"
RATE_NUM, RATE_DEN = 11, 500

# (amount_paise, expected fractional part, role)
PROBES: list[tuple[int, str, str]] = [
    (10341, ".502", "just above half — the narrowest test of the boundary"),
    (10205, ".510", "sweep"),
    (10251, ".522", "ALREADY MEASURED as +1 — re-mint would duplicate; see note"),
    (10070, ".540", "sweep"),
    (10480, ".560", "sweep — upper edge of the suspected zone"),
    (10300, ".600", "CONTROL: 71300p had .600 and matched ceiling exactly"),
    (10350, ".700", "CONTROL: expect +0"),
    (10450, ".900", "CONTROL: expect +0"),
    (20251, ".522", "REPLICATION of the +1 effect at a third magnitude"),
]
# 10251 was measured in batch 1; exclude it so the eight links are all new information.
PROBES = [p for p in PROBES if p[0] != 10251]


def frac_k(amount: int) -> int:
    return (amount * RATE_NUM) % RATE_DEN


def ceiling(amount: int) -> int:
    return int((Decimal(amount) * RATE_NUM / RATE_DEN).quantize(Decimal("1"), ROUND_CEILING))


def mint() -> None:
    auth = creds()
    existing = {}
    if REGISTRY.exists():
        for row in json.loads(REGISTRY.read_text()).get("links", []):
            existing[row["amount_paise"]] = row

    rows = []
    print(f"minting {len(PROBES) - len(existing)} probe links (throttled)\n")
    for amount, expected_frac, role in PROBES:
        k = frac_k(amount)
        assert f".{k*2:03d}"[:4] == expected_frac or abs(k / RATE_DEN - float(expected_frac)) < 1e-9, \
            f"{amount}: computed frac {k}/{RATE_DEN} != declared {expected_frac}"
        if amount in existing:
            rows.append(existing[amount]); continue
        link = create_link(auth, amount)
        if link is None:
            continue
        rows.append({"amount_paise": amount, "frac": k / RATE_DEN, "role": role,
                     "payment_link_id": link["id"], "short_url": link["short_url"],
                     "predicted_ceiling": ceiling(amount)})
        print(f"  ✓ {amount:>7}p  frac={k/RATE_DEN:.3f}  ceil={ceiling(amount):>4}p  "
              f"{link['short_url']}")
        time.sleep(THROTTLE_SECONDS)

    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY.write_text(json.dumps({
        "created_at": datetime.now(timezone.utc).isoformat(),
        "purpose": "map the fractional-part region where the fee exceeds ceiling (INCIDENTS.md #12)",
        "already_known": {"251": "+1", "10251": "+1", "10249": "+0", "10250": "+0"},
        "links": rows}, indent=2))

    items = "\n".join(
        f'<li><a href="{r["short_url"]}" target="_blank" rel="noopener">'
        f'<b>₹{r["amount_paise"]/100:,.2f}</b></a>'
        f'<span>frac <b>{r["frac"]:.3f}</b> · ceiling predicts {r["predicted_ceiling"]}p · '
        f'{r["role"]}</span></li>' for r in rows)
    PAGE.write_text(f"""<!doctype html><meta charset=utf-8>
<title>MILAAN · fee anomaly follow-up</title>
<style>body{{font:15px/1.6 ui-sans-serif,system-ui;max-width:860px;margin:3rem auto;padding:0 1rem}}
li{{margin:.6rem 0}} a{{font-variant-numeric:tabular-nums}} span{{color:#666;font-size:13px;margin-left:.6rem}}
code{{background:#f4f4f5;padding:.1rem .3rem;border-radius:3px}}
@media(prefers-color-scheme:dark){{body{{background:#0b0b0c;color:#e7e7e9}}span{{color:#9b9ba1}}code{{background:#1c1c1f}}}}</style>
<h1>Fee anomaly follow-up</h1>
<p>Test mode. Visa <code>4100 2800 0000 1007</code>, any future expiry, any CVV,
OTP any 4–10 digits.</p>
<p>These map the fractional part <code>k/500</code> of the exact fee. Only
<code>.522</code> has ever exceeded ceiling; these sweep <code>.502</code>–<code>.900</code>
at constant magnitude, with three controls that should come back matching ceiling.</p>
<ol>{items}</ol>
<p>Then: <code>uv run scripts/mint_followup.py --check</code></p>""")
    print(f"\n{len(rows)} links · registry {REGISTRY.relative_to(ROOT)}")
    print(f"open {PAGE.relative_to(ROOT)}")


def check() -> None:
    auth = creds()
    reg = json.loads(REGISTRY.read_text())
    captured = {}
    for p in api(auth, "GET", "/payments?count=100")[1].get("items", []):
        if p.get("status") == "captured":
            captured.setdefault(p["amount"], p)

    print(f"{'amount':>8} {'frac':>6} {'ceil':>6} {'actual':>7} {'delta':>6}  role")
    print("─" * 78)
    seen = []
    for row in sorted(reg["links"], key=lambda r: r["frac"]):
        amt = row["amount_paise"]
        p = captured.get(amt)
        if not p:
            print(f"{amt:>8} {row['frac']:>6.3f} {row['predicted_ceiling']:>6} {'—':>7} {'—':>6}  unpaid")
            continue
        base = (p.get("fee") or 0) - (p.get("tax") or 0)
        d = base - row["predicted_ceiling"]
        seen.append((row["frac"], d))
        print(f"{amt:>8} {row['frac']:>6.3f} {row['predicted_ceiling']:>6} {base:>7} "
              f"{d:>+6}  {row['role'][:38]}")
    print("─" * 78)
    if seen:
        plus = [f for f, d in seen if d > 0]
        zero = [f for f, d in seen if d == 0]
        print(f"  +1 at fracs: {sorted(plus)}")
        print(f"  +0 at fracs: {sorted(zero)}")
        if plus and zero:
            print(f"\n  the +1 region appears to be [{min(plus):.3f}, {max(plus):.3f}]")
            print("  update fees.py UNEXPLAINED and INCIDENTS.md #12 with this boundary")
        elif not plus:
            print("\n  no +1 reproduced — the original anomaly may be magnitude- or "
                  "time-dependent, not fractional. Say so; do not quietly drop it.")


if __name__ == "__main__":
    check() if "--check" in sys.argv else mint()
