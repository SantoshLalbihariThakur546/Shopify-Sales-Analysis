"""REST API. All endpoints are read-only (GET) and accept the same filter parameters:

  start=YYYY-MM-DD   end=YYYY-MM-DD
  product_type=...   (repeat the parameter for several values)
  province=...       gateway=...
  basis=incl_tax|excl_tax
  reveal_ids=true|false     (customer ids are masked unless true)
"""
from __future__ import annotations

import io
from datetime import datetime, timezone

import pandas as pd
from flask import Blueprint, Response, current_app, jsonify, request

from . import analytics as A
from .config import SALES_BASES
from .filters import FilterError, apply_filters, effective_range, parse_filters
from .insights import build_caveats, build_insights

bp = Blueprint("api", __name__, url_prefix="/api")


# ----------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------
def _store():
    return current_app.extensions["sales_store"]


def _context():
    """Parse filters and return (store, filters, filtered_df, (start, end))."""
    store = _store()
    f = parse_filters(request.args)
    df = apply_filters(store.df, f)
    window = effective_range(f, store.date_min, store.date_max)
    return store, f, df, window


def _top_limit() -> int:
    raw = request.args.get("limit", "10")
    try:
        return max(1, min(int(raw), 100))
    except ValueError:
        raise FilterError(f"'limit' must be a whole number, got '{raw}'.") from None


def _csv_safe(value):
    """Neutralise spreadsheet formula injection in exported text cells."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


def _csv_response(frame: pd.DataFrame, filename: str) -> Response:
    frame = frame.copy()
    for column in frame.columns:
        if frame[column].dtype == object or str(frame[column].dtype).startswith("str"):
            frame[column] = frame[column].map(_csv_safe)
    buffer = io.StringIO()
    frame.to_csv(buffer, index=False)
    return Response(
        buffer.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ----------------------------------------------------------------------------
# error handling
# ----------------------------------------------------------------------------
@bp.errorhandler(FilterError)
def _bad_request(err):
    return jsonify({"error": str(err)}), 400


# ----------------------------------------------------------------------------
# metadata
# ----------------------------------------------------------------------------
@bp.get("/health")
def health():
    store = _store()
    return jsonify(
        {
            "status": "ok",
            "rows": store.quality["rows_used"],
            "data_file": store.source_name,
            "date_min": store.date_min.isoformat(),
            "date_max": store.date_max.isoformat(),
        }
    )


@bp.get("/meta")
def meta():
    store = _store()
    return jsonify(
        {
            "date_min": store.date_min.isoformat(),
            "date_max": store.date_max.isoformat(),
            "days": store.quality["days"],
            "product_types": store.product_types,
            "provinces": store.provinces,
            "gateways": store.gateways,
            "bases": [{"id": k, "label": v["label"], "column": v["column"]} for k, v in SALES_BASES.items()],
            "data_file": store.source_name,
            "sheet": store.sheet_name,
            "currency": "USD",
        }
    )


@bp.get("/data-quality")
def data_quality():
    return jsonify(_store().quality)


# ----------------------------------------------------------------------------
# individual sections
# ----------------------------------------------------------------------------
@bp.get("/kpis")
def kpis():
    _, f, df, _ = _context()
    return jsonify({"filters": f.as_dict(), "kpis": A.kpis(df, f.sales_column)})


@bp.get("/sales/daily")
def sales_daily():
    _, f, df, (start, end) = _context()
    return jsonify({"filters": f.as_dict(), "rows": A.daily_sales(df, f.sales_column, start, end)})


@bp.get("/sales/hourly")
def sales_hourly():
    _, f, df, _ = _context()
    return jsonify({"filters": f.as_dict(), "rows": A.hourly_orders(df, f.sales_column)})


@bp.get("/products")
def products():
    _, f, df, _ = _context()
    return jsonify({"filters": f.as_dict(), **A.product_summary(df, f.sales_column)})


@bp.get("/customers/frequency")
def customers_frequency():
    _, f, df, _ = _context()
    return jsonify({"filters": f.as_dict(), **A.customer_frequency(df)})


@bp.get("/customers/top")
def customers_top():
    _, f, df, _ = _context()
    return jsonify(
        {
            "filters": f.as_dict(),
            "concentration": A.concentration(df, f.sales_column),
            "rows": A.top_customers(df, f.sales_column, _top_limit(), f.reveal_ids),
        }
    )


@bp.get("/geo/provinces")
def geo_provinces():
    _, f, df, _ = _context()
    return jsonify({"filters": f.as_dict(), **A.provinces(df, f.sales_column, _top_limit())})


@bp.get("/payments")
def payments():
    _, f, df, _ = _context()
    return jsonify({"filters": f.as_dict(), **A.gateways(df, f.sales_column)})


# ----------------------------------------------------------------------------
# everything in one round-trip (what the dashboard calls)
# ----------------------------------------------------------------------------
def build_dashboard(store, f, df, window) -> dict:
    start, end = window
    col = f.sales_column
    kpis = A.kpis(df, col)
    daily = A.daily_sales(df, col, start, end)
    products = A.product_summary(df, col)
    frequency = A.customer_frequency(df)
    concentration = A.concentration(df, col)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "filters": f.as_dict(),
        "basis": {"id": f.basis, "label": f.basis_label, "column": f.sales_column},
        "period": {"start": start.isoformat(), "end": end.isoformat(), "days": len(daily)},
        "kpis": kpis,
        "daily": daily,
        "hourly": A.hourly_orders(df, col),
        "products": products,
        "customers": {
            "frequency": frequency,
            "concentration": concentration,
            "top": A.top_customers(df, col, 10, f.reveal_ids),
        },
        "provinces": A.provinces(df, col, 10),
        "gateways": A.gateways(df, col),
        "insights": build_insights(
            kpis=kpis, daily=daily, products=products, frequency=frequency,
            concentration=concentration, basis_label=f.basis_label, start=start, end=end,
        ),
        "caveats": build_caveats(quality=store.quality, basis_label=f.basis_label, filtered=f.is_filtered),
        "quality": store.quality,
    }


@bp.get("/dashboard")
def dashboard():
    store, f, df, window = _context()
    return jsonify(build_dashboard(store, f, df, window))


@bp.get("/insights")
def insights():
    store, f, df, window = _context()
    payload = build_dashboard(store, f, df, window)
    return jsonify({"filters": payload["filters"], "insights": payload["insights"], "caveats": payload["caveats"]})


# ----------------------------------------------------------------------------
# CSV exports (aggregated, no personal data)
# ----------------------------------------------------------------------------
@bp.get("/export/daily.csv")
def export_daily():
    _, f, df, (start, end) = _context()
    rows = A.daily_sales(df, f.sales_column, start, end)
    frame = pd.DataFrame(rows).rename(
        columns={"date": "Order Date", "orders": "Orders", "sales": f"Sales ({f.basis_label})",
                 "customers": "Customers", "units": "Quantity"}
    )[["Order Date", "Orders", f"Sales ({f.basis_label})", "Customers", "Quantity"]]
    return _csv_response(frame, "daily_sales_summary.csv")


@bp.get("/export/products.csv")
def export_products():
    _, f, df, _ = _context()
    rows = A.product_summary(df, f.sales_column)["rows"]
    frame = pd.DataFrame(
        rows,
        columns=["product_type", "sales", "sales_incl_tax", "sales_excl_tax", "orders", "units",
                 "customers", "share"],
    ).rename(
        columns={
            "product_type": "Product Type", "sales": f"Sales ({f.basis_label})",
            "sales_incl_tax": "Total Price Usd (incl. tax)", "sales_excl_tax": "Subtotal Price (excl. tax)",
            "orders": "Orders", "units": "Quantity", "customers": "Customers", "share": "Share of sales",
        }
    )
    return _csv_response(frame, "product_sales_summary.csv")
