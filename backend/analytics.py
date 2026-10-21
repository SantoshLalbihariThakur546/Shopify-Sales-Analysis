"""Pure analytics over a (already filtered) sales DataFrame.

Definitions follow the project's DAX guide exactly:
  Total Sales (incl tax) = SUM(Total Price Usd)
  Sales Subtotal         = SUM(Subtotal Price)
  Total Orders           = DISTINCTCOUNT(Order Number)
  Unique Customers       = DISTINCTCOUNT(Customer Id)
  Average Order Value    = Total Sales / Total Orders
  Units Sold             = SUM(Quantity)
  Repeat customers       = customers with > 1 distinct order in the selected data

Every function returns plain Python types (never numpy / NaN) so the result
can be serialised straight to JSON.
"""
from __future__ import annotations

import math
from datetime import date

import pandas as pd

MONEY_DP = 2


# ----------------------------------------------------------------------------
# small helpers
# ----------------------------------------------------------------------------
def num(value, digits: int = MONEY_DP) -> float:
    """float(value) rounded, with NaN / inf / None mapped to 0.0."""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return 0.0
    if math.isnan(value) or math.isinf(value):
        return 0.0
    return round(value, digits)


def whole(value) -> int:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return 0
    return 0 if math.isnan(value) or math.isinf(value) else int(round(value))


def ratio(numerator, denominator, digits: int = 4) -> float:
    return num(numerator / denominator, digits) if denominator else 0.0


def ceil_pct(n: int, pct: int) -> int:
    """ceil(n * pct / 100) using integer arithmetic (avoids 30*0.1 == 3.0000000000000004)."""
    return (n * pct + 99) // 100


def day_label(d) -> str:
    return f"{d.strftime('%b')} {d.day}"


def mask_id(value) -> str:
    """Show at most the last 2 characters and never the whole id (ids here are 1-4 digits)."""
    text = str(value)
    keep = min(2, len(text) - 1)
    return "•••" + (text[-keep:] if keep > 0 else "")


# ----------------------------------------------------------------------------
# KPIs
# ----------------------------------------------------------------------------
def kpis(df: pd.DataFrame, sales_col: str) -> dict:
    if df.empty:
        return {
            "sales": 0.0, "sales_incl_tax": 0.0, "sales_excl_tax": 0.0, "tax": 0.0,
            "orders": 0, "customers": 0, "aov": 0.0, "units": 0,
            "repeat_customers": 0, "one_order_customers": 0, "repeat_share": 0.0,
            "avg_orders_per_customer": 0.0,
        }
    orders = int(df["Order Number"].nunique())
    customers = int(df["Customer Id"].nunique())
    sales = float(df[sales_col].sum())
    per_customer = df.groupby("Customer Id")["Order Number"].nunique()
    repeat = int((per_customer > 1).sum())
    return {
        "sales": num(sales),
        "sales_incl_tax": num(df["Total Price Usd"].sum()),
        "sales_excl_tax": num(df["Subtotal Price"].sum()),
        "tax": num(df["Total Tax"].sum()),
        "orders": orders,
        "customers": customers,
        "aov": num(sales / orders) if orders else 0.0,
        "units": whole(df["Quantity"].sum()),
        "repeat_customers": repeat,
        "one_order_customers": customers - repeat,
        "repeat_share": ratio(repeat, customers),
        "avg_orders_per_customer": num(per_customer.mean(), 2),
    }


# ----------------------------------------------------------------------------
# Time series
# ----------------------------------------------------------------------------
def daily_sales(df: pd.DataFrame, sales_col: str, start: date, end: date) -> list[dict]:
    """One row per calendar day in [start, end]; days without sales show zeros."""
    if start > end:
        return []
    days = pd.date_range(start, end, freq="D")
    if df.empty:
        grouped = pd.DataFrame(0.0, index=days, columns=["orders", "sales", "customers", "units"])
    else:
        grouped = (
            df.groupby("Order Date")
            .agg(
                orders=("Order Number", "nunique"),
                sales=(sales_col, "sum"),
                customers=("Customer Id", "nunique"),
                units=("Quantity", "sum"),
            )
            .reindex(days, fill_value=0)
        )
    rows = []
    for ts, rec in grouped.iterrows():
        rows.append(
            {
                "date": ts.date().isoformat(),
                "label": day_label(ts),
                "weekday": ts.strftime("%a"),
                "orders": whole(rec["orders"]),
                "sales": num(rec["sales"]),
                "customers": whole(rec["customers"]),
                "units": whole(rec["units"]),
            }
        )
    return rows


def hourly_orders(df: pd.DataFrame, sales_col: str) -> list[dict]:
    """Orders and sales by hour of day (0-23), using the timestamp as exported."""
    if df.empty:
        grouped = pd.DataFrame(0.0, index=range(24), columns=["orders", "sales"])
    else:
        grouped = (
            df.groupby("Order Hour")
            .agg(orders=("Order Number", "nunique"), sales=(sales_col, "sum"))
            .reindex(range(24), fill_value=0)
        )
    return [
        {"hour": int(h), "label": f"{int(h):02d}", "orders": whole(r["orders"]), "sales": num(r["sales"])}
        for h, r in grouped.iterrows()
    ]


# ----------------------------------------------------------------------------
# Products
# ----------------------------------------------------------------------------
def product_summary(df: pd.DataFrame, sales_col: str) -> dict:
    if df.empty:
        return {"rows": [], "count": 0, "top_product": None, "top3_share": 0.0}
    grouped = (
        df.groupby("Product Type")
        .agg(
            sales=(sales_col, "sum"),
            sales_incl_tax=("Total Price Usd", "sum"),
            sales_excl_tax=("Subtotal Price", "sum"),
            orders=("Order Number", "nunique"),
            units=("Quantity", "sum"),
            customers=("Customer Id", "nunique"),
        )
        .reset_index()
        .sort_values(["sales", "Product Type"], ascending=[False, True])
    )
    total = float(grouped["sales"].sum())
    rows, cumulative = [], 0.0
    for rec in grouped.itertuples(index=False):
        cumulative += float(rec.sales)
        rows.append(
            {
                "product_type": str(rec[0]),
                "sales": num(rec.sales),
                "sales_incl_tax": num(rec.sales_incl_tax),
                "sales_excl_tax": num(rec.sales_excl_tax),
                "orders": whole(rec.orders),
                "units": whole(rec.units),
                "customers": whole(rec.customers),
                "aov": num(rec.sales / rec.orders) if rec.orders else 0.0,
                "share": ratio(rec.sales, total),
                "cumulative_share": ratio(cumulative, total),
            }
        )
    top3 = sum(r["sales"] for r in rows[:3])
    return {
        "rows": rows,
        "count": len(rows),
        "top_product": rows[0]["product_type"],
        "top3_share": ratio(top3, total),
    }


# ----------------------------------------------------------------------------
# Customers
# ----------------------------------------------------------------------------
FREQUENCY_BUCKETS = [("1", 1, 1), ("2", 2, 2), ("3", 3, 3), ("4", 4, 4), ("5+", 5, None)]


def customer_frequency(df: pd.DataFrame) -> dict:
    """How many distinct orders each customer placed inside the selected window."""
    if df.empty:
        per_customer = pd.Series(dtype="int64")
    else:
        per_customer = df.groupby("Customer Id")["Order Number"].nunique()
    total = int(len(per_customer))
    buckets = []
    for label, low, high in FREQUENCY_BUCKETS:
        mask = per_customer >= low
        if high is not None:
            mask &= per_customer <= high
        count = int(mask.sum())
        buckets.append({"label": label, "customers": count, "share": ratio(count, total)})
    repeat = int((per_customer > 1).sum())
    return {
        "buckets": buckets,
        "total_customers": total,
        "repeat_customers": repeat,
        "one_order_customers": total - repeat,
        "repeat_share": ratio(repeat, total),
        "mean_orders": num(per_customer.mean(), 2) if total else 0.0,
        "median_orders": num(per_customer.median(), 1) if total else 0.0,
        "max_orders": int(per_customer.max()) if total else 0,
    }


def _customer_spend(df: pd.DataFrame, sales_col: str) -> pd.Series:
    return df.groupby("Customer Id")[sales_col].sum().sort_values(ascending=False)


def concentration(df: pd.DataFrame, sales_col: str) -> dict:
    """Share of sales from the top 10% / 20% of customers by spend (this window only)."""
    if df.empty:
        return {"customers": 0, "top10": {"n": 0, "share": 0.0}, "top20": {"n": 0, "share": 0.0}}
    spend = _customer_spend(df, sales_col)
    total = float(spend.sum())
    n = int(len(spend))

    def top(pct: int) -> dict:
        k = ceil_pct(n, pct)
        return {"n": k, "share": ratio(float(spend.head(k).sum()), total)}

    return {"customers": n, "top10": top(10), "top20": top(20)}


def top_customers(df: pd.DataFrame, sales_col: str, limit: int = 10, reveal: bool = False) -> list[dict]:
    if df.empty:
        return []
    grouped = (
        df.groupby("Customer Id")
        .agg(
            orders=("Order Number", "nunique"),
            spend=(sales_col, "sum"),
            units=("Quantity", "sum"),
            first=("Invoice Date", "min"),
            last=("Invoice Date", "max"),
        )
        .reset_index()
        .sort_values(["spend", "Customer Id"], ascending=[False, True])
        .head(limit)
    )
    total = float(df[sales_col].sum())
    rows = []
    for rank, rec in enumerate(grouped.itertuples(index=False), start=1):
        cid = rec[0]
        rows.append(
            {
                "rank": rank,
                "customer": str(cid) if reveal else mask_id(cid),
                "orders": whole(rec.orders),
                "spend": num(rec.spend),
                "units": whole(rec.units),
                "share": ratio(rec.spend, total),
                "first_purchase": rec.first.strftime("%Y-%m-%d %H:%M"),
                "last_purchase": rec.last.strftime("%Y-%m-%d %H:%M"),
            }
        )
    return rows


# ----------------------------------------------------------------------------
# Geography and payment
# ----------------------------------------------------------------------------
def _breakdown(df: pd.DataFrame, column: str, sales_col: str, limit: int | None) -> dict:
    if df.empty:
        return {"rows": [], "total_groups": 0, "other": None}
    grouped = (
        df.groupby(column)
        .agg(sales=(sales_col, "sum"), orders=("Order Number", "nunique"), customers=("Customer Id", "nunique"))
        .reset_index()
        .sort_values(["sales", column], ascending=[False, True])
    )
    total = float(grouped["sales"].sum())
    total_groups = int(len(grouped))
    head = grouped if limit is None else grouped.head(limit)
    rows = [
        {
            "name": str(r[0]),
            "sales": num(r.sales),
            "orders": whole(r.orders),
            "customers": whole(r.customers),
            "share": ratio(r.sales, total),
        }
        for r in head.itertuples(index=False)
    ]
    other = None
    if limit is not None and total_groups > limit:
        rest = grouped.iloc[limit:]
        other = {
            "name": f"Other ({len(rest)})",
            "sales": num(rest["sales"].sum()),
            "orders": whole(rest["orders"].sum()),
            "customers": None,  # distinct customers cannot be summed across groups
            "share": ratio(float(rest["sales"].sum()), total),
        }
    return {"rows": rows, "total_groups": total_groups, "other": other}


def provinces(df: pd.DataFrame, sales_col: str, limit: int = 10) -> dict:
    return _breakdown(df, "Province", sales_col, limit)


def gateways(df: pd.DataFrame, sales_col: str) -> dict:
    return _breakdown(df, "Gateway", sales_col, None)
