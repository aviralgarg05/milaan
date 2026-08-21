"""The canonical ledger shapes MILAAN reconciles against."""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field

from ..money import Paisa, ZERO

__all__ = ["LedgerEntry", "SettlementRow", "SETTLEMENT_TYPE", "NETTING_TYPES"]

SETTLEMENT_TYPE = "settlement"

# Entity types that participate in the netting identity. A settlement row is the
# *result* of the netting and is deliberately excluded from its own cover.
NETTING_TYPES = frozenset(
    {"payment", "refund", "adjustment", "transfer", "dispute", "reversal", "commission"}
)


@dataclass(frozen=True, slots=True)
class LedgerEntry:
    """One row of a Razorpay combined report.

    ``debit`` and ``credit`` are the ledger's own view and only one is ever
    non-zero. ``net`` is the signed contribution this row makes to a settlement:
    a captured payment credits the merchant, a refund debits them.
    """

    entity_id: str
    type: str
    debit: Paisa = ZERO
    credit: Paisa = ZERO
    amount: Paisa = ZERO
    fee: Paisa = ZERO
    tax: Paisa = ZERO
    currency: str = "INR"
    on_hold: bool = False
    settled: bool = False
    created_at: _dt.datetime | None = None
    settled_at: _dt.datetime | None = None
    settlement_id: str | None = None
    settlement_utr: str | None = None
    method: str | None = None
    payment_id: str | None = None
    order_id: str | None = None
    description: str | None = None
    extra: dict = field(default_factory=dict, compare=False)

    @property
    def net(self) -> Paisa:
        """Signed contribution to a settlement, in paise. Credit positive."""
        return Paisa(int(self.credit) - int(self.debit))

    @property
    def is_settlement(self) -> bool:
        return self.type == SETTLEMENT_TYPE

    @property
    def participates_in_netting(self) -> bool:
        return self.type in NETTING_TYPES


@dataclass(frozen=True, slots=True)
class SettlementRow:
    """One row of a settlements report — the bank-facing side of the ledger.

    Note that this is a *different file* from the combined report, and it is the
    only place a UTR appears: ``settlement_utr`` is null in every row of
    Razorpay's published combined sample. Joining these two is what recovers the
    bank reference, and MILAAN's anchor pass depends on it.
    """

    id: str
    amount: Paisa
    status: str | None = None
    fees: Paisa = ZERO
    tax: Paisa = ZERO
    utr: str | None = None
    created_at: _dt.datetime | None = None
    extra: dict = field(default_factory=dict, compare=False)
