#!/usr/bin/env python3
"""Day-1 GO/NO-GO probes. Read-only. Standard library only.

Run this the moment test keys exist. It answers, empirically, the four questions
the build plan is not allowed to assume:

  E1  Do the credentials authenticate against the REST API at all?
  E2  Are there any captured payments to reconcile yet?
  E3  Do test-mode payments carry a non-zero fee and tax?
  E4  Does test mode produce settlement objects?

E4 is the interesting one and it gates nothing. Razorpay's settlement docs say
"your account must be KYC approved" and "fully activated", and no documentation
states either way whether test mode generates settlements. Community reports
suggest empty. So MILAAN treats the sealed generator as PRIMARY ground truth and
promotes Razorpay-authored groupings to a second results column only if they
appear. An empty result here is expected and costs nothing; a non-empty result is
upside.

E3 matters more than it looks. If test-mode payments return fee=0, then the fee
model cannot be validated against Razorpay's own engine and has to be validated
against published pricing instead — which is a weaker claim that must be stated
out loud rather than quietly dropped.

    uv run scripts/check_keys.py

Nothing here writes. No orders created, no payments made, no money moved.
"""

from __future__ import annotations

import base64
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

API = "https://api.razorpay.com/v1"
ROOT = Path(__file__).resolve().parent.parent


def load_env() -> tuple[str, str]:
    key_id = os.environ.get("RAZORPAY_KEY_ID")
    secret = os.environ.get("RAZORPAY_KEY_SECRET")

    env_file = ROOT / ".env"
    if (not key_id or not secret) and env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, _, value = line.partition("=")
            value = value.strip().strip("'\"")
            if name.strip() == "RAZORPAY_KEY_ID" and not key_id:
                key_id = value
            elif name.strip() == "RAZORPAY_KEY_SECRET" and not secret:
                secret = value

    if not key_id or not secret:
        sys.exit(
            "No credentials found.\n"
            "  cp .env.example .env   and fill in your test keys, or export\n"
            "  RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET in the environment."
        )

    # Hard stop. This project has no business touching a live key, ever.
    if key_id.startswith("rzp_live_"):
        sys.exit(
            "REFUSING TO RUN: that is a LIVE key.\n"
            "MILAAN is a reconciliation harness that mints test transactions. "
            "Generate a test key from the dashboard's Test Mode toggle."
        )
    if not key_id.startswith("rzp_test_"):
        print(f"! warning: key id {key_id[:12]}... does not look like a test key\n")

    return key_id, secret


def get(path: str, auth: str, params: str = "") -> tuple[int, dict | str]:
    url = f"{API}{path}{params}"
    req = urllib.request.Request(url, headers={"Authorization": f"Basic {auth}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        try:
            return exc.code, json.loads(body)
        except json.JSONDecodeError:
            return exc.code, body
    except Exception as exc:  # network, DNS, timeout
        return 0, str(exc)


def rupees(paise: object) -> str:
    return f"₹{int(paise) / 100:,.2f}" if isinstance(paise, int) else str(paise)


def main() -> int:
    key_id, secret = load_env()
    auth = base64.b64encode(f"{key_id}:{secret}".encode()).decode()
    print(f"MILAAN Day-1 probes · key {key_id[:16]}…\n")

    verdicts: dict[str, str] = {}

    # ---- E1 authentication -------------------------------------------------
    status, body = get("/payments", auth, "?count=1")
    if status == 200:
        verdicts["E1 auth"] = "GREEN"
        print("E1  auth ................. GREEN  REST API accepts these credentials")
    elif status == 401:
        verdicts["E1 auth"] = "RED"
        print("E1  auth ................. RED    401 — key id/secret rejected.")
        print("      Regenerate from Test Mode → Account & Settings → API Keys.")
        return 1
    else:
        verdicts["E1 auth"] = "RED"
        print(f"E1  auth ................. RED    HTTP {status}: {body}")
        return 1

    # ---- E2 is there anything to reconcile? --------------------------------
    status, payments = get("/payments", auth, "?count=100")
    items = payments.get("items", []) if isinstance(payments, dict) else []
    captured = [p for p in items if p.get("status") == "captured"]
    print(f"E2  payments ............. {len(items)} total, {len(captured)} captured")
    if not captured:
        print("      No captured payments yet — expected on a fresh account.")
        print("      The offline half of MILAAN does not need any.")
    verdicts["E2 payments"] = "GREEN" if captured else "EMPTY"

    # ---- E3 does test mode charge a fee? -----------------------------------
    if captured:
        with_fee = [p for p in captured if p.get("fee")]
        sample = captured[0]
        print(
            f"E3  fee/tax .............. {len(with_fee)}/{len(captured)} carry a fee · "
            f"sample fee={rupees(sample.get('fee') or 0)} tax={rupees(sample.get('tax') or 0)}"
        )
        if with_fee:
            verdicts["E3 fee"] = "GREEN"
            print("      GREEN — the fee model can be validated against Razorpay's own engine.")
        else:
            verdicts["E3 fee"] = "RED"
            print("      RED — fee=0 in test mode. The fee model must be validated against")
            print("      published pricing instead, and DATA.md and the video must say so.")
    else:
        verdicts["E3 fee"] = "PENDING"
        print("E3  fee/tax .............. PENDING  needs at least one captured payment")

    # ---- E4 settlements: the one nobody has documented ---------------------
    status, settlements = get("/settlements", auth, "?count=100")
    if status == 200 and isinstance(settlements, dict):
        setl = settlements.get("items", [])
        if setl:
            verdicts["E4 settlements"] = "GREEN"
            total = sum(s.get("amount", 0) for s in setl)
            print(f"E4  settlements .......... GREEN  {len(setl)} settlements, {rupees(total)}")
            print("      Razorpay-authored groupings EXIST in test mode. This is upside:")
            print("      promote them to a second results column beside the sealed generator.")
        else:
            verdicts["E4 settlements"] = "EMPTY"
            print("E4  settlements .......... EMPTY  (expected; gates nothing)")
            print("      Settlement is T+2 working days and needs an activated account.")
            print("      Sealed generator stays PRIMARY. Re-run this daily — it may appear.")
    else:
        verdicts["E4 settlements"] = "ERROR"
        print(f"E4  settlements .......... HTTP {status}: {settlements}")

    # combined recon endpoint — the one that carries settlement_utr
    status, recon = get("/settlements/recon/combined", auth, "?year=2026&month=8")
    n = len(recon.get("items", [])) if isinstance(recon, dict) else 0
    print(f"E4b combined recon ....... HTTP {status}, {n} rows")

    print("\n" + "─" * 62)
    for name, verdict in verdicts.items():
        print(f"  {name:<18} {verdict}")
    print("─" * 62)
    print(
        "\nNothing here blocks the build. The solver, parsers, narration grammar\n"
        "and sealed ground truth are all offline. Record these results in\n"
        "DATA.md with today's date either way — a documented empty is evidence."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
