"""Load, validate and minimise the Shopify sales extract.

What this module guarantees
---------------------------
* The source file is never modified.
* Personal fields (customer first/last name, zip code) are NOT kept in memory,
  so they can never leak through the API.
* Missing Product Id / Variant Id values are counted and reported, never
  filled in with invented identifiers.
* Problems with the file produce a clear, actionable error message.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pandas as pd


class DataLoadError(Exception):
    """Raised when the sales file is missing, unreadable or has the wrong columns."""


# Columns that only exist in the "cleaned" workbook (added by the analyst) and
# therefore must not be counted as source columns.
HELPER_COLUMNS = {
    "Order Date", "Order Year", "Order Month", "Order Month Name", "Order Day", "Order Hour",
}

# Required for every metric on the dashboard.
REQUIRED_COLUMNS = [
    "Order Number", "Customer Id", "Invoice Date", "Product Type", "Quantity",
    "Subtotal Price", "Total Price Usd", "Total Tax",
]
NUMERIC_COLUMNS = ["Subtotal Price", "Total Price Usd", "Total Tax", "Quantity"]

# Optional columns: used when present, replaced by a neutral label when absent.
OPTIONAL_TEXT_COLUMNS = {
    "Billing Address Province": ("Province", "Unknown"),
    "Gateway": ("Gateway", "unknown"),
}


@dataclass
class SalesStore:
    """Everything the API needs, computed once at start-up."""

    df: pd.DataFrame
    quality: dict
    date_min: date
    date_max: date
    product_types: list = field(default_factory=list)
    provinces: list = field(default_factory=list)
    gateways: list = field(default_factory=list)
    source_name: str = ""
    sheet_name: str = ""


def _read_raw(path: Path, sheet: str):
    if not path.exists():
        raise DataLoadError(
            f"Data file not found: {path}\n"
            "Put your Shopify export in the 'data' folder, or set the environment "
            "variable SHOPIFY_DATA_FILE to its full path."
        )
    suffix = path.suffix.lower()
    try:
        if suffix == ".csv":
            return pd.read_csv(path), "csv"
        if suffix in (".xlsx", ".xlsm", ".xls"):
            with pd.ExcelFile(path) as workbook:
                names = list(workbook.sheet_names)
                if sheet:
                    if sheet not in names:
                        raise DataLoadError(f"Sheet '{sheet}' not found. Available sheets: {names}")
                    chosen = sheet
                else:
                    by_lower = {n.lower(): n for n in names}
                    chosen = by_lower.get("shopify_sales", names[0])
                return workbook.parse(chosen), chosen
    except DataLoadError:
        raise
    except Exception as exc:  # corrupt file, locked file, missing engine ...
        raise DataLoadError(f"Could not read '{path.name}': {exc}") from exc
    raise DataLoadError(f"Unsupported file type '{suffix}'. Use .xlsx or .csv.")


def _check(check_id: str, label: str, value, status: str, note: str) -> dict:
    return {"id": check_id, "label": label, "value": value, "status": status, "note": note}


def _clean_text(series: pd.Series, fallback: str) -> pd.Series:
    """Strip whitespace and give blank / missing values a visible label.

    Missing text must never be left as NaN: pandas groupby silently drops NaN keys,
    which would make product / state totals stop adding up to total sales.
    """
    cleaned = series.fillna("").astype(str).str.strip()
    return cleaned.mask(cleaned.str.lower().isin(["", "nan", "none", "null"]), fallback)


def load_sales_store(path: Path, sheet: str = "") -> SalesStore:
    raw, chosen_sheet = _read_raw(Path(path), sheet)
    raw.columns = [str(c).strip() for c in raw.columns]

    missing = [c for c in REQUIRED_COLUMNS if c not in raw.columns]
    if missing:
        raise DataLoadError(
            f"The file is missing required column(s): {missing}.\n"
            f"Columns found: {list(raw.columns)}"
        )
    if raw.empty:
        raise DataLoadError("The data file contains no rows.")

    # ---- facts about the raw file (before any cleaning) -----------------
    source_columns = [c for c in raw.columns if c not in HELPER_COLUMNS]
    total_rows = len(raw)
    duplicate_rows = int(raw.duplicated().sum())
    missing_product_id = int(raw["Product Id"].isna().sum()) if "Product Id" in raw else None
    missing_variant_id = int(raw["Variant Id"].isna().sum()) if "Variant Id" in raw else None
    id_cols = [c for c in ("Product Id", "Variant Id") if c in raw.columns]
    other_missing = int(raw.drop(columns=id_cols).isna().sum().sum())
    currencies = (
        sorted(raw["Currency"].dropna().astype(str).str.strip().unique())
        if "Currency" in raw.columns else []
    )

    # ---- type coercion ---------------------------------------------------
    invoice = pd.to_datetime(raw["Invoice Date"], errors="coerce")
    if getattr(invoice.dt, "tz", None) is not None:
        invoice = invoice.dt.tz_localize(None)  # keep wall-clock time as exported
    numeric = {c: pd.to_numeric(raw[c], errors="coerce") for c in NUMERIC_COLUMNS}

    bad = invoice.isna() | raw["Order Number"].isna() | raw["Customer Id"].isna()
    for series in numeric.values():
        bad |= series.isna()
    dropped_rows = int(bad.sum())
    keep = ~bad
    if not keep.any():
        raise DataLoadError("No usable rows after validation (check date and number formats).")

    gap = (numeric["Total Price Usd"] - (numeric["Subtotal Price"] + numeric["Total Tax"])).abs()
    max_gap = float(gap[keep].max())
    non_positive = int(((numeric["Quantity"] <= 0) | (numeric["Total Price Usd"] < 0))[keep].sum())

    # ---- minimised, analysis-ready frame (no names, no addresses) --------
    df = pd.DataFrame(
        {
            "Order Number": raw.loc[keep, "Order Number"],
            "Customer Id": raw.loc[keep, "Customer Id"],
            "Invoice Date": invoice[keep],
            "Product Type": raw.loc[keep, "Product Type"],
            "Quantity": numeric["Quantity"][keep],
            "Subtotal Price": numeric["Subtotal Price"][keep],
            "Total Price Usd": numeric["Total Price Usd"][keep],
            "Total Tax": numeric["Total Tax"][keep],
        }
    ).reset_index(drop=True)

    df["Order Date"] = df["Invoice Date"].dt.normalize()
    df["Order Hour"] = df["Invoice Date"].dt.hour
    df["Product Type"] = _clean_text(df["Product Type"], "Unspecified")
    for source_col, (target, fallback) in OPTIONAL_TEXT_COLUMNS.items():
        if source_col in raw.columns:
            values = _clean_text(raw.loc[keep, source_col].reset_index(drop=True), fallback)
        else:
            values = pd.Series([fallback] * len(df))
        df[target] = values

    # ---- lists for the filter dropdowns, biggest sellers first ------------
    def ranked(column: str) -> list:
        return (
            df.groupby(column)["Total Price Usd"].sum().sort_values(ascending=False).index.tolist()
        )

    date_min = df["Order Date"].min().date()
    date_max = df["Order Date"].max().date()
    distinct_orders = int(df["Order Number"].nunique())

    grain_ok = len(df) == distinct_orders
    checks = [
        _check(
            "missing_product_id", "Missing Product Id", missing_product_id,
            "ok" if not missing_product_id else "warn",
            "Left blank on purpose. IDs are never invented; this dashboard groups by Product Type.",
        ),
        _check(
            "missing_variant_id", "Missing Variant Id", missing_variant_id,
            "ok" if not missing_variant_id else "warn",
            "Left blank on purpose. Only matters for variant-level analysis.",
        ),
        _check(
            "other_missing", "Missing values in other columns", other_missing,
            "ok" if other_missing == 0 else "warn", "All remaining columns are fully populated."
            if other_missing == 0 else "Review the source file for blanks.",
        ),
        _check(
            "duplicates", "Exact duplicate rows", duplicate_rows,
            "ok" if duplicate_rows == 0 else "warn",
            "No exact duplicate rows found." if duplicate_rows == 0 else "Investigate duplicated records.",
        ),
        _check(
            "grain", "Rows vs distinct orders", f"{len(df):,} rows / {distinct_orders:,} orders",
            "ok" if grain_ok else "info",
            "One row per order number, so the row count equals the order count. Confirm the source "
            "grain with your team." if grain_ok else
            "Several rows share an order number (line items). Orders are counted as distinct Order Numbers.",
        ),
        _check(
            "reconciliation", "Total = Subtotal + Tax", f"max gap ${max_gap:.4f}",
            "ok" if max_gap < 0.01 else "warn",
            "Total Price Usd equals Subtotal Price + Total Tax to rounding precision."
            if max_gap < 0.01 else "Totals do not reconcile with subtotal + tax.",
        ),
        _check(
            "currency", "Currency", ", ".join(currencies) if currencies else "not provided",
            "ok" if len(currencies) == 1 else "info",
            "Single currency; amounts are formatted as USD." if len(currencies) == 1
            else "Amounts use the 'Total Price Usd' column.",
        ),
        _check(
            "invalid_rows", "Rows dropped (bad date / number / id)", dropped_rows,
            "ok" if dropped_rows == 0 else "warn",
            "Every row was usable." if dropped_rows == 0 else "These rows were excluded from all metrics.",
        ),
        _check(
            "non_positive", "Rows with quantity <= 0 or negative total", non_positive,
            "ok" if non_positive == 0 else "warn",
            "No refunds or negative rows detected." if non_positive == 0 else "Check for returns/refunds.",
        ),
    ]

    quality = {
        "rows": total_rows,
        "rows_used": int(len(df)),
        "source_columns": len(source_columns),
        "distinct_orders": distinct_orders,
        "unique_customers": int(df["Customer Id"].nunique()),
        "product_types": int(df["Product Type"].nunique()),
        "date_min": date_min.isoformat(),
        "date_max": date_max.isoformat(),
        "days": (date_max - date_min).days + 1,
        "checks": checks,
        "missing_product_id": missing_product_id,
        "missing_variant_id": missing_variant_id,
    }

    return SalesStore(
        df=df,
        quality=quality,
        date_min=date_min,
        date_max=date_max,
        product_types=ranked("Product Type"),
        provinces=ranked("Province"),
        gateways=ranked("Gateway"),
        source_name=Path(path).name,
        sheet_name=str(chosen_sheet),
    )
