"""Generate the written insights + recommendations shown on the dashboard.

The wording mirrors the five findings in the project report, but every number is
recomputed from the currently filtered data. Rules the text must respect:
  * one week of data => no claims about seasonality, retention or lifetime value
  * say which revenue definition (incl./excl. tax) is being shown
"""
from __future__ import annotations

from datetime import date


def money(value: float, digits: int = 2) -> str:
    return f"${value:,.{digits}f}"


def pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def fmt_date(d: date) -> str:
    return f"{d.day} {d.strftime('%b %Y')}"


def period_label(start: date, end: date) -> str:
    if start == end:
        return fmt_date(start)
    if (start.year, start.month) == (end.year, end.month):
        return f"{start.day}–{end.day} {end.strftime('%b %Y')}"
    return f"{fmt_date(start)} – {fmt_date(end)}"


def build_insights(*, kpis: dict, daily: list, products: dict, frequency: dict,
                   concentration: dict, basis_label: str, start: date, end: date) -> list[dict]:
    if kpis["orders"] == 0:
        return [
            {
                "id": "no-data",
                "tag": "No data",
                "title": "No orders match the current filters",
                "finding": "The selected date range, product types, states and payment gateways "
                           "contain no orders.",
                "recommendation": "Widen the date range or clear one or more filters.",
                "visual": "Filter bar",
            }
        ]

    insights = []
    period = period_label(start, end)
    tax_phrase = "including tax" if basis_label == "incl. tax" else "excluding tax"

    # 1) headline ------------------------------------------------------------
    finding = (
        f"Recorded sales {tax_phrase} totalled {money(kpis['sales'])} across "
        f"{kpis['orders']:,} distinct orders ({period}); average order value was {money(kpis['aov'])}."
    )
    if len(daily) >= 2:
        high = max(daily, key=lambda r: r["sales"])
        low = min(daily, key=lambda r: r["sales"])
        if high["sales"] != low["sales"]:
            finding += (
                f" The highest day was {high['label']} ({money(high['sales'])}) and the lowest was "
                f"{low['label']} ({money(low['sales'])}) — a comparison within this {len(daily)}-day "
                f"window, not evidence of seasonality."
            )
    insights.append(
        {
            "id": "sales-headline",
            "tag": "Sales",
            "title": "Headline sales performance",
            "finding": finding,
            "recommendation": "Use the KPI cards as the dashboard headline and always label the period "
                              "and whether tax is included.",
            "visual": "KPI cards · Recorded sales by date",
        }
    )

    # 2) leading product -----------------------------------------------------
    rows = products["rows"]
    if rows:
        lead = rows[0]
        if len(rows) == 1:
            finding = (
                f"The current selection contains a single product type, {lead['product_type']}: "
                f"{money(lead['sales'])} from {lead['units']:,} units."
            )
        else:
            finding = (
                f"{lead['product_type']} was the largest product type at {money(lead['sales'])} "
                f"({pct(lead['share'])} of recorded sales, {lead['units']:,} units)."
            )
        insights.append(
            {
                "id": "top-product",
                "tag": "Products",
                "title": "Leading product type",
                "finding": finding,
                "recommendation": "Review inventory availability and merchandising for the leading "
                                  "categories; compare units and margin if cost data becomes available.",
                "visual": "Revenue by product type",
            }
        )

    # 3) concentration across product types ---------------------------------
    if len(rows) >= 3:
        names = ", ".join(r["product_type"] for r in rows[:3])
        insights.append(
            {
                "id": "product-concentration",
                "tag": "Products",
                "title": "Sales are concentrated in a few categories",
                "finding": f"The top three product types ({names}) together accounted for "
                           f"{pct(products['top3_share'])} of recorded sales.",
                "recommendation": "Keep the sorted product chart visible so stakeholders can see how "
                                  "concentrated sales are by category.",
                "visual": "Revenue by product type · Product table",
            }
        )

    # 4) repeat customers ----------------------------------------------------
    if frequency["total_customers"] > 0:
        insights.append(
            {
                "id": "repeat-customers",
                "tag": "Customers",
                "title": "Repeat purchasing within the period",
                "finding": (
                    f"{frequency['repeat_customers']:,} of {frequency['total_customers']:,} customers "
                    f"({pct(frequency['repeat_share'])}) placed more than one distinct order in this window; "
                    f"{frequency['one_order_customers']:,} placed one. Orders per customer: mean "
                    f"{frequency['mean_orders']:.2f}, median {frequency['median_orders']:g}, "
                    f"maximum {frequency['max_orders']}."
                ),
                "recommendation": "Treat this as within-period repeat activity only. Obtain several months "
                                  "of data before making any retention claim.",
                "visual": "Customer order frequency",
            }
        )

    # 5) top-customer concentration -----------------------------------------
    if concentration["customers"] >= 10:
        top10, top20 = concentration["top10"], concentration["top20"]
        insights.append(
            {
                "id": "customer-concentration",
                "tag": "Customers",
                "title": "Top-customer concentration",
                "finding": (
                    f"The top 10% of customers by recorded spend (n={top10['n']:,}) contributed "
                    f"{pct(top10['share'])} of sales; the top 20% (n={top20['n']:,}) contributed "
                    f"{pct(top20['share'])}."
                ),
                "recommendation": "Explore customer-level value carefully and validate identifiers; do not "
                                  "assume this short-window ranking predicts long-term customer value.",
                "visual": "Top-customer concentration · Top customers",
            }
        )

    return insights


def build_caveats(*, quality: dict, basis_label: str, filtered: bool) -> list[str]:
    days = quality["days"]
    caveats = [
        f"The data covers {days} day{'s' if days != 1 else ''} "
        f"({period_label(date.fromisoformat(quality['date_min']), date.fromisoformat(quality['date_max']))}) only. "
        "It describes this extract; it cannot establish seasonality, long-term retention, cohorts or "
        "customer lifetime value.",
        ("Sales include the recorded tax (Total Price Usd = Subtotal Price + Total Tax)."
         if basis_label == "incl. tax" else
         "Sales exclude tax (Subtotal Price). Switch the basis to include tax (Total Price Usd)."),
        "A customer's first purchase in this extract is not necessarily their first purchase ever.",
        "Customer names and addresses are never loaded; customer IDs are masked unless you reveal them.",
    ]
    if quality.get("missing_product_id") or quality.get("missing_variant_id"):
        caveats.append(
            f"Product Id is missing on {quality.get('missing_product_id') or 0} rows and Variant Id on "
            f"{quality.get('missing_variant_id') or 0} rows. They are left blank, not invented."
        )
    if filtered:
        caveats.append("Filters are active: every figure on this page describes the filtered subset only.")
    return caveats
