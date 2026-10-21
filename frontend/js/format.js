// Number / date formatting helpers (display only; the backend sends raw numbers).
const usd0 = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
const usd2 = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 2 });
const int = new Intl.NumberFormat("en-US");

export const money0 = (v) => usd0.format(v || 0);
export const money2 = (v) => usd2.format(v || 0);
export const num = (v) => int.format(Math.round(v || 0));
export const pct1 = (v) => `${((v || 0) * 100).toFixed(1)}%`;
export const pct2 = (v) => `${((v || 0) * 100).toFixed(2)}%`;

/** $1.62M, $752K, $2.8K, $950 - short labels for axes and bars. */
export function moneyCompact(v) {
  const n = Math.abs(v || 0);
  const sign = v < 0 ? "-" : "";
  if (n >= 1e6) return `${sign}$${(n / 1e6).toFixed(n >= 1e7 ? 1 : 2)}M`;
  if (n >= 1e4) return `${sign}$${Math.round(n / 1e3)}K`;
  if (n >= 1e3) return `${sign}$${(n / 1e3).toFixed(1).replace(/\.0$/, "")}K`;
  return `${sign}$${Math.round(n)}`;
}

export const intCompact = (v) => {
  const n = Math.abs(v || 0);
  if (n >= 1e4) return `${Math.round(n / 1e3)}K`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(1).replace(/\.0$/, "")}K`;
  return String(Math.round(n));
};

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
function parts(iso) {
  const [y, m, d] = iso.split("-").map(Number);
  return { y, m, d };
}
export function fmtDay(iso) {
  const { m, d } = parts(iso);
  return `${MONTHS[m - 1]} ${d}`;
}
export function fmtRange(startIso, endIso) {
  const a = parts(startIso), b = parts(endIso);
  if (startIso === endIso) return `${a.d} ${MONTHS[a.m - 1]} ${a.y}`;
  if (a.y === b.y && a.m === b.m) return `${a.d}–${b.d} ${MONTHS[b.m - 1]} ${b.y}`;
  return `${a.d} ${MONTHS[a.m - 1]} ${a.y} – ${b.d} ${MONTHS[b.m - 1]} ${b.y}`;
}

/** shopify_payments -> Shopify Payments */
export const prettyName = (s) =>
  String(s).replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
/** Escape text before putting it into innerHTML. */
export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ESC[c]);
