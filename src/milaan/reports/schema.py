"""Canonical field names for Razorpay ledger exports, and the three dialects.

Razorpay exposes the same settlement ledger under three different naming
conventions, and they are not interchangeable:

  1. **XLSX report headers** — what you get from a downloaded combined report.
     ``transaction_entity``, ``fee (exclusive tax)``, ``payment_method``.
  2. **API parameters** — what ``/v1/settlements/recon/combined`` returns.
     ``type``, ``fee``, ``method``, plus ``posted_at`` and ``credit_type`` which
     the XLSX does not carry.
  3. **Dashboard custom-report headers** — Title Case with expanded labels.
     ``Settlement ID``, ``UTR (Unique Transaction Reference)``.

They also differ in *content*, not just naming: ``settlement_utr`` is present as
a column in the combined XLSX but null in every row of Razorpay's own published
sample, while the API's combined endpoint does populate it. So the XLSX path has
to join the combined report to the settlements report to recover a UTR, and the
API path does not. Both mappers ship, and a round-trip test pins them.
"""

from __future__ import annotations

__all__ = ["CANONICAL", "DIALECTS", "canonicalise_header", "detect_dialect"]

# Canonical internal names. Everything downstream of the loader speaks only these.
CANONICAL = (
    "entity_id",
    "type",
    "debit",
    "credit",
    "amount",
    "currency",
    "fee",
    "tax",
    "on_hold",
    "settled",
    "created_at",
    "settled_at",
    "posted_at",
    "settlement_id",
    "settlement_utr",
    "description",
    "notes",
    "payment_id",
    "order_id",
    "order_receipt",
    "arn",
    "dispute_id",
    "method",
    "card_network",
    "card_issuer",
    "card_type",
    "credit_type",
    # settlements-report.xlsx uses a flatter shape of its own
    "status",
    "fees",
    "utr",
)

# alias -> canonical. Keys are matched case-insensitively with whitespace and
# punctuation normalised, so "UTR (Unique Transaction Reference)" and "utr" both land.
DIALECTS: dict[str, dict[str, str]] = {
    "xlsx_combined": {
        "transaction_entity": "type",
        "entity_id": "entity_id",
        "fee (exclusive tax)": "fee",
        "fee exclusive tax": "fee",
        "payment_method": "method",
        "settlement_utr": "settlement_utr",
    },
    "api_combined": {
        "type": "type",
        "fee": "fee",
        "method": "method",
        "posted_at": "posted_at",
        "credit_type": "credit_type",
    },
    "dashboard": {
        "settlement id": "settlement_id",
        "utr (unique transaction reference)": "utr",
        "transaction entity": "type",
        "entity id": "entity_id",
        "fee (exclusive tax)": "fee",
        "payment method": "method",
        "created at": "created_at",
        "settled at": "settled_at",
        "order receipt": "order_receipt",
        "card network": "card_network",
        "card issuer": "card_issuer",
        "card type": "card_type",
        "dispute id": "dispute_id",
        "payment id": "payment_id",
        "order id": "order_id",
    },
}

# Flattened alias table: every dialect's aliases plus the identity mapping.
_ALIAS: dict[str, str] = {}
for _d in DIALECTS.values():
    _ALIAS.update(_d)
for _c in CANONICAL:
    _ALIAS.setdefault(_c, _c)


def _normalise(header: str) -> str:
    return " ".join(str(header).strip().lower().replace("_", " ").split())


# Rebuild the alias table on normalised keys so "Settlement ID", "settlement_id"
# and "settlement id" all resolve identically.
_NORM_ALIAS = {_normalise(k): v for k, v in _ALIAS.items()}


def canonicalise_header(header: str) -> str | None:
    """Map one export header to its canonical name, or None if unrecognised.

    Unrecognised headers are preserved by the loader under their raw name rather
    than dropped — a column MILAAN does not model is not the same as a column
    that does not exist, and silently discarding one is how a reconciliation
    engine loses money.
    """
    if header is None:
        return None
    return _NORM_ALIAS.get(_normalise(header))


def detect_dialect(headers: list[str]) -> str:
    """Best-guess the dialect of a header row, for diagnostics and reporting."""
    norm = {_normalise(h) for h in headers if h}
    if "transaction entity" in norm and "fee exclusive tax" in norm:
        return "xlsx_combined"
    if "posted at" in norm or "credit type" in norm:
        return "api_combined"
    if any(h and str(h)[:1].isupper() for h in headers if h) and "settlement id" in norm:
        return "dashboard"
    if {"id", "amount", "status", "fees", "tax", "utr"} <= norm:
        return "xlsx_settlements"
    return "unknown"
