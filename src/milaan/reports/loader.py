"""Load Razorpay XLSX exports into canonical ledger rows.

Every defensive step here exists because Razorpay's own published sample files
break the obvious version of this code. They are documented as they occur, and
each one is pinned by a test in ``tests/test_sample_reports.py``:

  * ``sample-settlements-report.xlsx`` has a **blank column A** — the headers
    start at B1 — plus 19 trailing all-``None`` columns. A naive
    ``pandas.read_excel`` silently shifts every column by one and the file
    parses "successfully" into garbage.
  * ``created_at`` and ``settled_at`` mix native ``datetime`` objects with
    strings in three different formats, in the same column. See ``dates.py``.
  * Money arrives as rupee floats. See ``money.py``.
  * ``settlement_utr`` exists as a column but is null in 14 of 14 rows.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

from ..money import ZERO, from_report_rupees
from .dates import parse_datetime
from .models import LedgerEntry, SettlementRow
from .schema import canonicalise_header, detect_dialect

__all__ = ["load_sheet", "load_combined_report", "load_settlements_report", "SheetLoadResult"]

_TRUTHY = {"true", "yes", "y", "1"}
_FALSEY = {"false", "no", "n", "0", ""}


class SheetLoadResult(list):
    """Rows plus the diagnostics a reconciliation run has to report on."""

    def __init__(self, rows: list[dict], *, dialect: str, headers: list[str],
                 header_row: int, dropped_columns: list[str], ambiguous_dates: int,
                 unrecognised_headers: list[str]) -> None:
        super().__init__(rows)
        self.dialect = dialect
        self.headers = headers
        self.header_row = header_row
        self.dropped_columns = dropped_columns
        self.ambiguous_dates = ambiguous_dates
        self.unrecognised_headers = unrecognised_headers


def _cells(path: Path | str, sheet: int = 0) -> list[list[Any]]:
    import openpyxl

    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    try:
        ws = wb.worksheets[sheet]
        return [[c.value for c in row] for row in ws.iter_rows()]
    finally:
        wb.close()


def _find_header_row(grid: list[list[Any]]) -> int:
    """First row carrying more than two non-empty cells.

    Razorpay exports sometimes carry a title or blank rows above the header. Any
    row with three or more populated cells is a header; a two-cell row is more
    likely a title or a stray note.
    """
    for i, row in enumerate(grid):
        if sum(1 for c in row if c is not None and str(c).strip() != "") > 2:
            return i
    raise ValueError("no header row found: the sheet has no row with >2 populated cells")


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in _TRUTHY:
        return True
    if text in _FALSEY:
        return False
    return False


def load_sheet(path: Path | str, sheet: int = 0) -> SheetLoadResult:
    """Read one sheet into canonicalised dicts, preserving unknown columns."""
    grid = _cells(path, sheet)
    if not grid:
        return SheetLoadResult([], dialect="empty", headers=[], header_row=-1,
                               dropped_columns=[], ambiguous_dates=0, unrecognised_headers=[])

    hi = _find_header_row(grid)
    raw_headers = grid[hi]

    # Keep only columns that actually have a header. This is what defuses the
    # blank column A and the trailing all-None columns: we index by *header
    # position*, never by ordinal, so a leading empty column cannot shift the row.
    live = [(i, str(h).strip()) for i, h in enumerate(raw_headers)
            if h is not None and str(h).strip() != ""]
    dropped = [f"col{i}" for i, h in enumerate(raw_headers)
               if h is None or str(h).strip() == ""]

    headers = [h for _, h in live]
    dialect = detect_dialect(headers)
    unrecognised = [h for h in headers if canonicalise_header(h) is None]

    rows: list[dict] = []
    ambiguous = 0
    for raw in grid[hi + 1:]:
        if all(raw[i] is None or str(raw[i]).strip() == "" for i, _ in live if i < len(raw)):
            continue
        row: dict[str, Any] = {}
        for i, header in live:
            value = raw[i] if i < len(raw) else None
            key = canonicalise_header(header) or header
            if key in {"created_at", "settled_at", "posted_at"}:
                parsed = parse_datetime(value)
                ambiguous += int(parsed.ambiguous)
                row[key] = parsed.value
                row[f"_{key}_raw"] = parsed.raw
            else:
                row[key] = value
        rows.append(row)

    return SheetLoadResult(rows, dialect=dialect, headers=headers, header_row=hi,
                           dropped_columns=dropped, ambiguous_dates=ambiguous,
                           unrecognised_headers=unrecognised)


_ENTRY_FIELDS = {f for f in LedgerEntry.__dataclass_fields__ if f != "extra"}


def load_combined_report(path: Path | str, sheet: int = 0) -> list[LedgerEntry]:
    """Load a combined settlement report into ``LedgerEntry`` rows."""
    result = load_sheet(path, sheet)
    return [_to_entry(row) for row in result]


def _to_entry(row: dict) -> LedgerEntry:
    known = {}
    extra = {}
    for key, value in row.items():
        if key.startswith("_"):
            extra[key] = value
        elif key in _ENTRY_FIELDS:
            known[key] = value
        else:
            extra[key] = value

    for money_field in ("debit", "credit", "amount", "fee", "tax"):
        known[money_field] = from_report_rupees(known.get(money_field))
    for flag in ("on_hold", "settled"):
        known[flag] = _to_bool(known.get(flag))
    for text_field in ("entity_id", "type"):
        known[text_field] = str(known.get(text_field) or "").strip()
    for opt in ("settlement_id", "settlement_utr", "method", "payment_id",
                "order_id", "description", "currency"):
        value = known.get(opt)
        known[opt] = str(value).strip() if value is not None and str(value).strip() else None
    if known.get("currency") is None:
        known["currency"] = "INR"

    return LedgerEntry(**{k: v for k, v in known.items() if k in _ENTRY_FIELDS}, extra=extra)


def load_settlements_report(path: Path | str, sheet: int = 0) -> list[SettlementRow]:
    """Load a settlements report — the only export carrying the bank UTR."""
    out = []
    for row in load_sheet(path, sheet):
        out.append(
            SettlementRow(
                id=str(row.get("id") or row.get("entity_id") or "").strip(),
                amount=from_report_rupees(row.get("amount")),
                status=(str(row["status"]).strip() if row.get("status") else None),
                fees=from_report_rupees(row.get("fees") if "fees" in row else row.get("fee")),
                tax=from_report_rupees(row.get("tax")),
                utr=(str(row["utr"]).strip() if row.get("utr") else None),
                created_at=row.get("created_at"),
                extra={k: v for k, v in row.items() if k.startswith("_")},
            )
        )
    return out


def group_by_settlement(entries: list[LedgerEntry]) -> dict[str, list[LedgerEntry]]:
    """Members keyed by the settlement they belong to.

    Settlement rows are excluded: a settlement is not a member of itself. This is
    the join that a naive ``groupby('settlement_id')`` gets wrong, because
    settlement rows carry ``settlement_id = None`` and their own id lives in
    ``entity_id`` — so they collect into a spurious ``None`` bucket and every
    real group appears to be missing its total.
    """
    out: dict[str, list[LedgerEntry]] = {}
    for entry in entries:
        if entry.is_settlement or not entry.settlement_id:
            continue
        out.setdefault(entry.settlement_id, []).append(entry)
    return out


def settlement_rows(entries: list[LedgerEntry]) -> dict[str, LedgerEntry]:
    """Settlement rows keyed by their own ``entity_id``."""
    return {e.entity_id: e for e in entries if e.is_settlement}
