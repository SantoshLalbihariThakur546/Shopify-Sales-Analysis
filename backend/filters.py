"""Parse and apply the dashboard slicers (the equivalent of Power BI slicers)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

import pandas as pd

from .config import DEFAULT_BASIS, SALES_BASES


class FilterError(ValueError):
    """Invalid query parameters. Surfaces to the client as HTTP 400."""


@dataclass(frozen=True)
class Filters:
    start: date | None = None
    end: date | None = None
    product_types: tuple = ()
    provinces: tuple = ()
    gateways: tuple = ()
    basis: str = DEFAULT_BASIS
    reveal_ids: bool = False

    @property
    def sales_column(self) -> str:
        return SALES_BASES[self.basis]["column"]

    @property
    def basis_label(self) -> str:
        return SALES_BASES[self.basis]["label"]

    @property
    def is_filtered(self) -> bool:
        return bool(self.start or self.end or self.product_types or self.provinces or self.gateways)

    def as_dict(self) -> dict:
        return {
            "start": self.start.isoformat() if self.start else None,
            "end": self.end.isoformat() if self.end else None,
            "product_type": list(self.product_types),
            "province": list(self.provinces),
            "gateway": list(self.gateways),
            "basis": self.basis,
            "reveal_ids": self.reveal_ids,
        }


def _parse_date(raw: str | None, name: str) -> date | None:
    if raw is None or raw.strip() == "":
        return None
    try:
        return datetime.strptime(raw.strip(), "%Y-%m-%d").date()
    except ValueError:
        raise FilterError(f"'{name}' must be a date in YYYY-MM-DD format, got '{raw}'.") from None


def _clean_list(values) -> tuple:
    seen, out = set(), []
    for value in values:
        value = (value or "").strip()
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return tuple(out)


def parse_filters(args) -> Filters:
    """Build a Filters object from a Flask `request.args` (MultiDict)."""
    start = _parse_date(args.get("start"), "start")
    end = _parse_date(args.get("end"), "end")
    if start and end and start > end:
        raise FilterError("'start' must be on or before 'end'.")

    basis = (args.get("basis") or DEFAULT_BASIS).strip()
    if basis not in SALES_BASES:
        raise FilterError(f"'basis' must be one of {sorted(SALES_BASES)}, got '{basis}'.")

    reveal = str(args.get("reveal_ids", "")).strip().lower() in {"1", "true", "yes", "on"}

    return Filters(
        start=start,
        end=end,
        product_types=_clean_list(args.getlist("product_type")),
        provinces=_clean_list(args.getlist("province")),
        gateways=_clean_list(args.getlist("gateway")),
        basis=basis,
        reveal_ids=reveal,
    )


def apply_filters(df: pd.DataFrame, f: Filters) -> pd.DataFrame:
    mask = pd.Series(True, index=df.index)
    if f.start:
        mask &= df["Order Date"] >= pd.Timestamp(f.start)
    if f.end:
        mask &= df["Order Date"] <= pd.Timestamp(f.end)
    if f.product_types:
        mask &= df["Product Type"].isin(f.product_types)
    if f.provinces:
        mask &= df["Province"].isin(f.provinces)
    if f.gateways:
        mask &= df["Gateway"].isin(f.gateways)
    return df[mask]


def effective_range(f: Filters, data_min: date, data_max: date) -> tuple[date, date]:
    """The calendar window the charts should cover (clamped to the data's own range)."""
    start = max(f.start, data_min) if f.start else data_min
    end = min(f.end, data_max) if f.end else data_max
    return start, end
