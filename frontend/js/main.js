// Dashboard controller: state, filters, API calls and rendering.
import { getJSON } from "./api.js";
import * as C from "./charts.js";
import { CONFIG } from "./config.js";
import * as F from "./format.js";
import { MultiSelect } from "./ui.js";

const $ = (selector, root = document) => root.querySelector(selector);
const { esc } = F;

const state = {
  meta: null,
  filters: { start: "", end: "", product_type: [], province: [], gateway: [] },
  basis: "incl_tax",
  reveal: false,
  data: null,        // /api/dashboard result (filtered)
  ctxDaily: [],      // daily rows ignoring the date filter (so every day stays clickable)
  ctxProducts: [],   // product rows ignoring the product filter (so every bar stays clickable)
  sort: { key: "sales", dir: "desc" },
  controller: null,
  timer: null,
  widgets: {},
};

// ---------------------------------------------------------------------------
// query string <-> state
// ---------------------------------------------------------------------------
function buildParams({ omit = [], forUrl = false } = {}) {
  const p = new URLSearchParams();
  const f = state.filters;
  if (!omit.includes("start") && f.start) p.set("start", f.start);
  if (!omit.includes("end") && f.end) p.set("end", f.end);
  if (!omit.includes("product_type")) f.product_type.forEach((v) => p.append("product_type", v));
  f.province.forEach((v) => p.append("province", v));
  f.gateway.forEach((v) => p.append("gateway", v));
  if (!forUrl || state.basis !== "incl_tax") p.set("basis", state.basis);
  if (state.reveal) p.set("reveal_ids", "true");
  return p;
}

function normalizeDates() {
  const { date_min: min, date_max: max } = state.meta;
  const f = state.filters;
  const isDate = (s) => /^\d{4}-\d{2}-\d{2}$/.test(s);
  if (!isDate(f.start)) f.start = "";
  if (!isDate(f.end)) f.end = "";
  if (f.start && f.start < min) f.start = min;
  if (f.end && f.end > max) f.end = max;
  if (f.start && f.start > max) f.start = max;
  if (f.end && f.end < min) f.end = min;
  if (f.start && f.end && f.start > f.end) f.end = f.start;
  if (f.start === min) f.start = "";   // "from the first day" is the same as no filter
  if (f.end === max) f.end = "";
}

function readUrl() {
  const p = new URLSearchParams(location.search);
  const f = state.filters;
  const known = (list, values) => values.filter((v) => list.includes(v));
  f.start = p.get("start") || "";
  f.end = p.get("end") || "";
  f.product_type = known(state.meta.product_types, p.getAll("product_type"));
  f.province = known(state.meta.provinces, p.getAll("province"));
  f.gateway = known(state.meta.gateways, p.getAll("gateway"));
  state.basis = p.get("basis") === "excl_tax" ? "excl_tax" : "incl_tax";
  state.reveal = p.get("reveal_ids") === "true";
  normalizeDates();
}

function writeUrl() {
  const query = buildParams({ forUrl: true }).toString();
  history.replaceState(null, "", query ? `?${query}` : location.pathname);
}

const hasFilters = () => {
  const f = state.filters;
  return !!(f.start || f.end || f.product_type.length || f.province.length || f.gateway.length);
};

// ---------------------------------------------------------------------------
// controls
// ---------------------------------------------------------------------------
function afterFilterChange() {
  normalizeDates();
  syncControls();
  writeUrl();
  scheduleRefresh();
}

function syncControls() {
  const { date_min: min, date_max: max } = state.meta;
  const f = state.filters;
  const start = $("#f-start");
  const end = $("#f-end");
  start.min = end.min = min;
  start.max = end.max = max;
  start.value = f.start || min;
  end.value = f.end || max;
  state.widgets.products.setSelected(f.product_type);
  state.widgets.provinces.setSelected(f.province);
  state.widgets.gateways.setSelected(f.gateway);
  $("#reset-btn").disabled = !hasFilters();
  $("#reveal-ids").checked = state.reveal;
  document.querySelectorAll("#basis-toggle button").forEach((b) =>
    b.setAttribute("aria-pressed", String(b.dataset.basis === state.basis)),
  );
  renderChips();
}

function renderChips() {
  const host = $("#chips");
  const f = state.filters;
  const { date_min: min, date_max: max } = state.meta;
  const chips = [];
  if (f.start || f.end) chips.push({ label: `Dates: ${F.fmtRange(f.start || min, f.end || max)}`, remove: () => { f.start = ""; f.end = ""; } });
  f.product_type.forEach((v) => chips.push({ label: v, remove: () => (f.product_type = f.product_type.filter((x) => x !== v)) }));
  f.province.forEach((v) => chips.push({ label: v, remove: () => (f.province = f.province.filter((x) => x !== v)) }));
  f.gateway.forEach((v) => chips.push({ label: F.prettyName(v), remove: () => (f.gateway = f.gateway.filter((x) => x !== v)) }));
  host.replaceChildren();
  chips.forEach((chip) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "chip";
    b.setAttribute("aria-label", `Remove filter ${chip.label}`);
    b.innerHTML = `${esc(chip.label)} <b aria-hidden="true">×</b>`;
    b.addEventListener("click", () => { chip.remove(); afterFilterChange(); });
    host.appendChild(b);
  });
}

function initControls() {
  const { meta } = state;
  const f = state.filters;

  $("#f-start").addEventListener("change", (e) => {
    f.start = e.target.value;
    if (f.start && f.end && f.start > f.end) f.end = f.start;
    afterFilterChange();
  });
  $("#f-end").addEventListener("change", (e) => {
    f.end = e.target.value;
    if (f.end && f.start && f.end < f.start) f.start = f.end;
    afterFilterChange();
  });

  state.widgets.products = new MultiSelect($("#f-products"), {
    label: "Product type", allLabel: "All product types",
    options: meta.product_types.map((v) => ({ value: v, label: v })),
    onChange: (values) => { f.product_type = values; afterFilterChange(); },
  });
  state.widgets.provinces = new MultiSelect($("#f-provinces"), {
    label: "State", allLabel: "All states",
    options: meta.provinces.map((v) => ({ value: v, label: v })),
    onChange: (values) => { f.province = values; afterFilterChange(); },
  });
  state.widgets.gateways = new MultiSelect($("#f-gateways"), {
    label: "Payment gateway", allLabel: "All gateways",
    options: meta.gateways.map((v) => ({ value: v, label: F.prettyName(v) })),
    onChange: (values) => { f.gateway = values; afterFilterChange(); },
  });

  $("#reset-btn").addEventListener("click", () => {
    f.start = f.end = "";
    f.product_type = []; f.province = []; f.gateway = [];
    afterFilterChange();
  });

  document.querySelectorAll("#basis-toggle button").forEach((b) =>
    b.addEventListener("click", () => {
      if (state.basis === b.dataset.basis) return;
      state.basis = b.dataset.basis;
      afterFilterChange();
    }),
  );

  $("#reveal-ids").addEventListener("change", (e) => {
    state.reveal = e.target.checked;
    afterFilterChange();
  });

  // export menu
  const exportBtn = $("#export-btn");
  const exportPop = $("#export-pop");
  exportBtn.addEventListener("click", () => {
    exportPop.hidden = !exportPop.hidden;
    exportBtn.setAttribute("aria-expanded", String(!exportPop.hidden));
  });
  document.addEventListener("click", (e) => {
    if (!$("#export-menu").contains(e.target)) {
      exportPop.hidden = true;
      exportBtn.setAttribute("aria-expanded", "false");
    }
  });

  // table sorting (event delegation, header is re-rendered on every refresh)
  $("#product-table thead").addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-key]");
    if (!btn) return;
    const key = btn.dataset.key;
    state.sort = state.sort.key === key
      ? { key, dir: state.sort.dir === "asc" ? "desc" : "asc" }
      : { key, dir: key === "product_type" ? "asc" : "desc" };
    renderTable();
  });

  let resizeTimer;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => state.data && renderKpis(), 200);
  });
}

function initTheme() {
  const btn = $("#theme-btn");
  const apply = (dark) => {
    document.documentElement.setAttribute("data-theme", dark ? "dark" : "light");
    btn.setAttribute("aria-label", dark ? "Switch to light mode" : "Switch to dark mode");
  };
  apply(document.documentElement.getAttribute("data-theme") === "dark");
  btn.addEventListener("click", () => {
    const dark = document.documentElement.getAttribute("data-theme") !== "dark";
    apply(dark);
    try { localStorage.setItem("theme", dark ? "dark" : "light"); } catch { /* storage blocked */ }
  });
}

// ---------------------------------------------------------------------------
// loading / errors
// ---------------------------------------------------------------------------
function setLoading(on) {
  $("#main").classList.toggle("is-loading", on);
  $("#main").setAttribute("aria-busy", String(on));
}

function showError(message, retry) {
  const banner = $("#error-banner");
  banner.hidden = false;
  banner.innerHTML = `<span><strong>Something went wrong.</strong> ${esc(message)}</span><button type="button">Try again</button>`;
  banner.querySelector("button").addEventListener("click", retry);
}
const hideError = () => { $("#error-banner").hidden = true; };

function scheduleRefresh() {
  clearTimeout(state.timer);
  state.timer = setTimeout(refresh, CONFIG.DEBOUNCE_MS);
}

async function refresh() {
  state.controller?.abort();
  const controller = new AbortController();
  state.controller = controller;
  setLoading(true);
  try {
    const f = state.filters;
    const main = getJSON("/api/dashboard", buildParams(), controller.signal);
    // Charts that act as slicers keep showing every option, with the current choice highlighted.
    const dailyCtx = f.start || f.end ? getJSON("/api/sales/daily", buildParams({ omit: ["start", "end"] }), controller.signal) : null;
    const prodCtx = f.product_type.length ? getJSON("/api/products", buildParams({ omit: ["product_type"] }), controller.signal) : null;
    const [data, dctx, pctx] = await Promise.all([main, dailyCtx, prodCtx]);
    if (controller !== state.controller) return;
    state.data = data;
    state.ctxDaily = dctx ? dctx.rows : data.daily;
    state.ctxProducts = pctx ? pctx.rows : data.products.rows;
    hideError();
    render();
  } catch (err) {
    if (err.name === "AbortError") return;
    showError(err.message, refresh);
  } finally {
    if (controller === state.controller) setLoading(false);
  }
}

// ---------------------------------------------------------------------------
// rendering
// ---------------------------------------------------------------------------
function render() {
  const d = state.data;
  $("#period-pill").textContent = `${F.fmtRange(d.quality.date_min, d.quality.date_max)} · ${d.quality.days} days`;
  $("#notice-text").innerHTML =
    `<strong>${d.quality.days} days of data (${esc(F.fmtRange(d.quality.date_min, d.quality.date_max))}).</strong> ` +
    "Figures describe this extract only — they are not evidence of seasonality, long-term retention or customer lifetime value.";
  const query = buildParams().toString();
  $("#export-daily").href = `${CONFIG.API_BASE}/api/export/daily.csv?${query}`;
  $("#export-products").href = `${CONFIG.API_BASE}/api/export/products.csv?${query}`;

  renderKpis();
  renderDaily();
  renderProducts();
  renderFrequency();
  renderConcentration();
  renderHourly();
  renderProvinces();
  renderGateways();
  renderInsights();
  renderQuality();
  renderTable();
  $("#footer-meta").textContent =
    `Source: ${state.meta.data_file} (sheet “${state.meta.sheet}”) · ${F.num(d.quality.rows_used)} rows analysed · ` +
    `generated ${new Date(d.generated_at).toLocaleString()} · all amounts in USD`;
}

function renderKpiSkeleton() {
  $("#kpis").innerHTML = Array.from({ length: 6 }, () =>
    '<article class="kpi"><div class="skeleton" style="height:12px;width:60%"></div>' +
    '<div class="skeleton" style="height:28px;width:80%;margin-top:12px"></div>' +
    '<div class="skeleton" style="height:10px;width:70%;margin-top:12px"></div></article>').join("");
}

function renderKpis() {
  const d = state.data;
  const k = d.kpis;
  const basis = d.basis.label;
  const perOrder = k.orders ? k.units / k.orders : 0;
  const cards = [
    {
      label: `Total sales (${basis})`, value: F.money0(k.sales), title: F.money2(k.sales), accent: true,
      sub: d.basis.id === "incl_tax"
        ? `Subtotal ${F.money2(k.sales_excl_tax)} + tax ${F.money2(k.tax)}`
        : `Including tax: ${F.money2(k.sales_incl_tax)}`,
      spark: d.daily.map((r) => r.sales),
    },
    { label: "Distinct orders", value: F.num(k.orders), sub: "Distinct Order Numbers", spark: d.daily.map((r) => r.orders) },
    { label: "Unique customers", value: F.num(k.customers), sub: `${F.num(k.repeat_customers)} placed 2+ orders` },
    { label: "Average order value", value: F.money2(k.aov), sub: `Sales ÷ orders (${basis})` },
    { label: "Units sold", value: F.num(k.units), sub: `${perOrder.toFixed(2)} units per order` },
    { label: "Repeat-customer share", value: F.pct1(k.repeat_share), sub: "Within this period only — not retention" },
  ];
  const host = $("#kpis");
  host.innerHTML = cards.map((c) =>
    `<article class="kpi${c.accent ? " accent" : ""}${c.spark ? " has-spark" : ""}">` +
    `<div class="kpi-label">${esc(c.label)}</div>` +
    `<div class="kpi-value" title="${esc(c.title || c.value)}">${esc(c.value)}</div>` +
    `<div class="kpi-sub">${esc(c.sub)}</div>` +
    `${c.spark ? '<div class="kpi-spark"></div>' : ""}</article>`).join("");
  host.querySelectorAll(".kpi").forEach((card, i) => {
    const spot = card.querySelector(".kpi-spark");
    if (spot) C.sparkline(spot, cards[i].spark);
  });
}

function renderDaily() {
  const f = state.filters;
  const { date_min: min, date_max: max } = state.meta;
  const basis = state.data.basis.label;
  const hasSel = !!(f.start || f.end);
  const lo = f.start || min;
  const hi = f.end || max;
  const single = hasSel && lo === hi;
  $("#daily-sub").textContent = !hasSel
    ? "Click a day to filter the whole dashboard"
    : single
      ? `Showing ${F.fmtRange(lo, hi)} · click that day again to clear`
      : `Highlighted ${F.fmtRange(lo, hi)} · click a day to focus on it`;

  C.areaLineChart($("#chart-daily"), {
    data: state.ctxDaily, height: 360,
    x: (r) => r.label, x2: (r) => r.weekday, y: (r) => r.sales,
    hasSelection: hasSel, isSelected: (r) => r.date >= lo && r.date <= hi,
    tooltip: (r) => `<b>${esc(r.weekday)}, ${esc(r.label)}</b><br>Sales (${esc(basis)}): <b>${F.money2(r.sales)}</b><br>` +
      `<span class="t-muted">${F.num(r.orders)} orders · ${F.num(r.customers)} customers · ${F.num(r.units)} units</span>`,
    onSelect: (r) => toggleDay(r.date),
    pointLabel: (r) => `${r.weekday} ${r.label}: ${F.money0(r.sales)} in sales. Activate to filter to this day.`,
    ariaLabel: `Recorded sales by date, ${F.fmtRange(min, max)}`,
  });
}

function toggleDay(date) {
  const f = state.filters;
  const { date_min: min, date_max: max } = state.meta;
  const alreadySingle = (f.start || min) === date && (f.end || max) === date;
  if (alreadySingle) { f.start = ""; f.end = ""; } else { f.start = date; f.end = date; }
  afterFilterChange();
}

function toggleProduct(name) {
  const f = state.filters;
  f.product_type = f.product_type.includes(name) ? f.product_type.filter((x) => x !== name) : [...f.product_type, name];
  afterFilterChange();
}

function renderProducts() {
  const selected = new Set(state.filters.product_type);
  const basis = state.data.basis.label;
  $("#products-sub").textContent = selected.size
    ? `${selected.size} selected · click a bar to add or remove`
    : `Sales ${basis} · click a bar to filter`;
  const sharePct = (s) => (s < 0.01 ? `${(s * 100).toFixed(1)}%` : `${Math.round(s * 100)}%`);

  C.hBarChart($("#chart-products"), {
    data: state.ctxProducts, rowHeight: 28,
    label: (r) => r.product_type, value: (r) => r.sales, rightExtra: (r) => sharePct(r.share),
    hasSelection: selected.size > 0, isSelected: (r) => selected.has(r.product_type),
    tooltip: (r) => `<b>${esc(r.product_type)}</b><br>Sales (${esc(basis)}): <b>${F.money2(r.sales)}</b> · ${F.pct1(r.share)}<br>` +
      `<span class="t-muted">${F.num(r.orders)} orders · ${F.num(r.units)} units · ${F.num(r.customers)} customers<br>Avg order ${F.money2(r.aov)}</span>`,
    onSelect: (r) => toggleProduct(r.product_type),
    rowLabel: (r) => `${r.product_type}: ${F.money0(r.sales)}, ${F.pct1(r.share)} of sales. Activate to filter.`,
    ariaLabel: "Revenue by product type, sorted from highest to lowest",
  });
}

function renderFrequency() {
  const fr = state.data.customers.frequency;
  C.columnChart($("#chart-frequency"), {
    data: fr.buckets, height: 340, xTitle: "Distinct orders placed in the period",
    label: (b) => b.label, value: (b) => b.customers, fmtValue: (v) => F.num(v),
    barClass: (b) => (b.label === "1" ? "alt" : ""),
    tooltip: (b) => `<b>${esc(b.label)} order${b.label === "1" ? "" : "s"}</b><br>${F.num(b.customers)} customers (${F.pct1(b.share)})`,
    pointLabel: (b) => `${b.label} orders: ${b.customers} customers`,
    ariaLabel: "Number of customers by orders placed in the period",
  });
  $("#frequency-stats").innerHTML =
    `<div class="stat"><b>${F.num(fr.repeat_customers)}</b><span>repeat customers (${F.pct1(fr.repeat_share)})</span></div>` +
    `<div class="stat"><b>${fr.mean_orders.toFixed(2)} / ${esc(fr.median_orders)}</b><span>mean / median orders</span></div>` +
    `<div class="stat"><b>${F.num(fr.max_orders)}</b><span>most orders by one customer</span></div>`;
}

function renderConcentration() {
  const { concentration: c, top } = state.data.customers;
  const body = $("#conc-body");
  if (!c.customers) {
    body.innerHTML = '<div class="empty" style="grid-column:1/-1">No customers in the current selection</div>';
  } else {
    body.innerHTML = [[10, c.top10], [20, c.top20]].map(([pct, t]) =>
      `<div class="meter"><div class="meter-top"><b>${F.pct1(t.share)}</b><span>of sales from the top ${pct}% of customers</span></div>` +
      `<div class="meter-bar" role="img" aria-label="Top ${pct} percent of customers contribute ${F.pct1(t.share)} of sales"><i style="width:${(t.share * 100).toFixed(1)}%"></i></div>` +
      `<p class="meter-note">${F.num(t.n)} of ${F.num(c.customers)} customers · within this period only, not lifetime value</p></div>`).join("");
  }
  $("#top-customers tbody").innerHTML = top.length
    ? top.map((r) =>
      `<tr><td>${r.rank}</td><td class="${r.customer.startsWith("•") ? "mask" : ""}">${esc(r.customer)}</td>` +
      `<td class="num">${F.num(r.orders)}</td><td class="num">${F.num(r.units)}</td><td class="num">${F.money2(r.spend)}</td>` +
      `<td class="num">${F.pct2(r.share)}</td><td>${esc(r.last_purchase)}</td></tr>`).join("")
    : '<tr><td colspan="7" class="empty">No customers in the current selection</td></tr>';
}

function renderHourly() {
  const rows = state.data.hourly;
  const peak = Math.max(...rows.map((r) => r.orders));
  C.columnChart($("#chart-hourly"), {
    data: rows, height: 250, xEvery: 3, maxBar: 24, xTitle: "Hour of day (00–23)",
    label: (r) => r.label, value: (r) => r.orders,
    barClass: (r) => (r.orders === peak ? "" : "alt"),
    tooltip: (r) => `<b>${r.label}:00–${r.label}:59</b><br>${F.num(r.orders)} orders<br><span class="t-muted">${F.money2(r.sales)} in sales</span>`,
    pointLabel: (r) => `${r.label}:00 hour: ${r.orders} orders`,
    ariaLabel: "Orders by hour of day; the busiest hour is highlighted in green",
  });
}

function renderProvinces() {
  const p = state.data.provinces;
  const basis = state.data.basis.label;
  $("#chart-provinces").previousElementSibling.querySelector(".sub").textContent =
    p.total_groups ? `Billing province · top ${p.rows.length} of ${p.total_groups}` : "Billing province";
  const rows = p.rows.map((r) => ({ ...r }));
  if (p.other) rows.push({ ...p.other, __static: true, __note: true });
  C.hBarChart($("#chart-provinces"), {
    data: rows, rowHeight: 26, labelWidth: 132, rightWidth: 86,
    label: (r) => r.name, value: (r) => r.sales, rightExtra: (r) => `${Math.round(r.share * 100)}%`,
    tooltip: (r) => `<b>${esc(r.name)}</b><br>Sales (${esc(basis)}): <b>${F.money2(r.sales)}</b> · ${F.pct1(r.share)}<br><span class="t-muted">${F.num(r.orders)} orders</span>`,
    rowLabel: (r) => `${r.name}: ${F.money0(r.sales)}`,
    ariaLabel: "Sales by billing state, top ten",
  });
}

function renderGateways() {
  const rows = state.data.gateways.rows;
  const basis = state.data.basis.label;
  const total = rows.reduce((s, r) => s + r.sales, 0);
  C.donutChart($("#chart-gateways"), {
    data: rows, value: (r) => r.sales, label: (r) => F.prettyName(r.name), legendValue: (r) => F.pct1(r.share),
    centerTop: F.moneyCompact(total), centerBottom: "total",
    tooltip: (r) => `<b>${esc(F.prettyName(r.name))}</b><br>${F.money2(r.sales)} (${esc(basis)}) · ${F.pct1(r.share)}<br><span class="t-muted">${F.num(r.orders)} orders</span>`,
    itemLabel: (r) => `${F.prettyName(r.name)}: ${F.pct1(r.share)} of sales`,
    ariaLabel: "Share of sales by payment gateway",
  });
}

function renderInsights() {
  $("#insights-list").innerHTML = state.data.insights.map((i) =>
    `<li class="insight"><div class="insight-top"><span class="tag">${esc(i.tag)}</span><h3>${esc(i.title)}</h3></div>` +
    `<p class="finding">${esc(i.finding)}</p>` +
    `<p class="rec"><b>Recommendation:</b><span>${esc(i.recommendation)}</span></p>` +
    `<p class="visual">Backed by: <span>${esc(i.visual)}</span></p></li>`).join("");
}

function renderQuality() {
  const icons = { ok: "✓", warn: "!", info: "i" };
  $("#quality-list").innerHTML = state.data.quality.checks.map((c) =>
    `<li class="q-${esc(c.status)}"><span class="q-ico" aria-hidden="true">${icons[c.status] || "i"}</span>` +
    `<div><div class="q-label">${esc(c.label)}</div><div class="q-note">${esc(c.note)}</div></div>` +
    `<div class="q-value">${esc(c.value ?? "n/a")}</div></li>`).join("");
  $("#caveats-list").innerHTML = state.data.caveats.map((c) => `<li>${esc(c)}</li>`).join("");
}

const TABLE_COLUMNS = [
  { key: "product_type", label: "Product type", text: true },
  { key: "sales", label: "Sales" },
  { key: "share", label: "% of sales" },
  { key: "orders", label: "Orders" },
  { key: "units", label: "Units" },
  { key: "customers", label: "Customers" },
  { key: "aov", label: "Avg order" },
];

function renderTable() {
  const d = state.data;
  const rows = [...d.products.rows];
  const { key, dir } = state.sort;
  rows.sort((a, b) => {
    const cmp = typeof a[key] === "string" ? a[key].localeCompare(b[key]) : a[key] - b[key];
    return dir === "asc" ? cmp : -cmp;
  });
  const maxShare = Math.max(...rows.map((r) => r.share), 0.0001);
  const table = $("#product-table");
  table.querySelector("thead").innerHTML = "<tr>" + TABLE_COLUMNS.map((c) => {
    const active = c.key === key;
    const arrow = active ? (dir === "asc" ? "▲" : "▼") : "";
    return `<th class="${c.text ? "" : "num"}" aria-sort="${active ? (dir === "asc" ? "ascending" : "descending") : "none"}">` +
      `<button type="button" data-key="${c.key}">${esc(c.label)} ${arrow}</button></th>`;
  }).join("") + "</tr>";

  table.querySelector("tbody").innerHTML = rows.length ? rows.map((r) =>
    `<tr><td>${esc(r.product_type)}</td><td class="num">${F.money2(r.sales)}</td>` +
    `<td class="num"><div class="share-cell"><i style="width:${Math.max(2, (r.share / maxShare) * 80).toFixed(0)}px"></i><span>${F.pct1(r.share)}</span></div></td>` +
    `<td class="num">${F.num(r.orders)}</td><td class="num">${F.num(r.units)}</td><td class="num">${F.num(r.customers)}</td>` +
    `<td class="num">${F.money2(r.aov)}</td></tr>`).join("")
    : '<tr><td colspan="7" class="empty">No products in the current selection</td></tr>';

  table.querySelector("tfoot")?.remove();
  if (rows.length) {
    const k = d.kpis;
    const foot = document.createElement("tfoot");
    foot.innerHTML =
      `<tr class="total-row"><td>Total</td><td class="num">${F.money2(k.sales)}</td><td class="num">100.0%</td>` +
      `<td class="num">${F.num(k.orders)}</td><td class="num">${F.num(k.units)}</td><td class="num">${F.num(k.customers)}</td>` +
      `<td class="num">${F.money2(k.aov)}</td></tr>`;
    table.appendChild(foot);
  }
}

// ---------------------------------------------------------------------------
// start-up
// ---------------------------------------------------------------------------
async function init() {
  initTheme();
  renderKpiSkeleton();
  hideError();
  try {
    state.meta = await getJSON("/api/meta");
  } catch (err) {
    showError(err.message, () => location.reload());
    return;
  }
  readUrl();
  initControls();
  syncControls();
  writeUrl();
  refresh();
}

init();
