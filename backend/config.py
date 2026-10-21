"""Central configuration. Every value can be overridden with an environment variable."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Where the sales extract lives. Point SHOPIFY_DATA_FILE at the original
# "Shopify Sales.xlsx" (sheet "shopify_sales") or at the cleaned workbook.
DATA_FILE = Path(os.getenv("SHOPIFY_DATA_FILE", BASE_DIR / "data" / "Shopify_Sales_Cleaned.xlsx"))

# Optional: force a specific Excel sheet. Empty = auto-detect
# ("shopify_sales" if present, otherwise the first sheet).
SHEET_NAME = os.getenv("SHOPIFY_SHEET", "").strip()

FRONTEND_DIR = BASE_DIR / "frontend"

# Same-origin by default (Flask serves the dashboard itself), so CORS is off.
# Only set this if you host the frontend on a different origin, e.g.
#   CORS_ORIGINS=http://127.0.0.1:5500
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]

# Sales basis choices exposed to the UI. Total Price Usd already includes tax.
SALES_BASES = {
    "incl_tax": {"column": "Total Price Usd", "label": "incl. tax"},
    "excl_tax": {"column": "Subtotal Price", "label": "excl. tax"},
}
DEFAULT_BASIS = "incl_tax"
