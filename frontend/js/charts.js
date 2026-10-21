// Small dependency-free SVG chart library (area/line, horizontal bars, columns, donut, sparkline).
// Colours come from CSS variables, so light/dark themes switch without redrawing.
import { esc, intCompact, moneyCompact } from "./format.js";

const NS = "http://www.w3.org/2000/svg";
let uid = 0;

function el(tag, attrs, parent) {
  const node = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v !== undefined && v !== null) node.setAttribute(k, v);
  }
  if (parent) parent.appendChild(node);
  return node;
}

// ---------------------------------------------------------------------------
// tooltip (a single shared element, see index.html)
// ---------------------------------------------------------------------------
export function showTip(html, evt) {
  const tip = document.getElementById("tooltip");
  tip.innerHTML = html;
  tip.hidden = false;
  moveTip(evt);
}
export function moveTip(evt) {
  const tip = document.getElementById("tooltip");
  const pad = 14;
  const box = tip.getBoundingClientRect();
  let x = evt.clientX + pad;
  let y = evt.clientY + pad;
  if (x + box.width > window.innerWidth - 8) x = evt.clientX - box.width - pad;
  if (y + box.height > window.innerHeight - 8) y = evt.clientY - box.height - pad;
  tip.style.left = `${Math.max(8, x)}px`;
  tip.style.top = `${Math.max(8, y)}px`;
}
export function hideTip() {
  document.getElementById("tooltip").hidden = true;
}
function tipAtNode(node, html) {
  const r = node.getBoundingClientRect();
  showTip(html, { clientX: r.left + r.width / 2, clientY: r.top });
}

/** Make an SVG element hoverable, focusable and (optionally) clickable. */
function interactive(node, { tooltip, onSelect, label }) {
  if (tooltip) {
    node.addEventListener("mouseenter", (e) => showTip(tooltip(), e));
    node.addEventListener("mousemove", moveTip);
    node.addEventListener("mouseleave", hideTip);
    node.addEventListener("focus", () => tipAtNode(node, tooltip()));
    node.addEventListener("blur", hideTip);
  }
  if (onSelect) {
    node.setAttribute("role", "button");
    node.setAttribute("tabindex", "0");
    if (label) node.setAttribute("aria-label", label);
    node.addEventListener("click", () => { hideTip(); onSelect(); });
    node.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSelect(); }
    });
  } else if (tooltip) {
    node.setAttribute("tabindex", "0");
    if (label) { node.setAttribute("role", "img"); node.setAttribute("aria-label", label); }
  }
}

// ---------------------------------------------------------------------------
// responsive redraw: re-render a chart when its container's width changes
// ---------------------------------------------------------------------------
const observer = new ResizeObserver((entries) => {
  for (const entry of entries) {
    const node = entry.target;
    const width = Math.round(entry.contentRect.width);
    if (node.__render && node.__width !== width) {
      node.__width = width;
      node.__render();
    }
  }
});
function mount(node, render) {
  node.__render = render;
  if (!node.__observed) {
    observer.observe(node);
    node.__observed = true;
  }
  render();
  node.__width = Math.round(node.clientWidth);
}

export function showEmpty(node, message = "No orders match the current filters") {
  node.__render = null;
  node.replaceChildren();
  const div = document.createElement("div");
  div.className = "empty";
  div.textContent = message;
  node.appendChild(div);
}

const widthOf = (node, min = 240) => Math.max(Math.floor(node.clientWidth), min);

/** "Nice" axis maximum and step for a given data maximum. */
export function niceScale(max, ticks = 4) {
  if (!(max > 0)) return { max: 1, step: 1 / ticks };
  const rough = max / ticks;
  const pow = Math.pow(10, Math.floor(Math.log10(rough)));
  const frac = rough / pow;
  const nice = frac <= 1 ? 1 : frac <= 2 ? 2 : frac <= 2.5 ? 2.5 : frac <= 5 ? 5 : 10;
  const step = nice * pow;
  return { max: Math.ceil(max / step - 1e-9) * step, step };
}

function truncate(text, limit) {
  const s = String(text);
  return s.length > limit ? `${s.slice(0, limit - 1)}…` : s;
}

// ---------------------------------------------------------------------------
// area + line chart (zero-based so the visual size of changes is honest)
// ---------------------------------------------------------------------------
export function areaLineChart(node, o) {
  const data = o.data || [];
  if (!data.length || data.every((d) => !(o.y(d) > 0))) return showEmpty(node, o.emptyText);
  const gid = `grad${++uid}`;

  mount(node, () => {
    node.replaceChildren();
    const W = widthOf(node, 300);
    const H = o.height || 340;
    const m = { l: 56, r: 18, t: 26, b: 44 };
    const iw = W - m.l - m.r;
    const ih = H - m.t - m.b;
    const scale = niceScale(Math.max(...data.map(o.y)), 4);
    const pad = Math.min(30, iw / (data.length * 2));
    const xAt = (i) => (data.length === 1 ? m.l + iw / 2 : m.l + pad + (i * (iw - 2 * pad)) / (data.length - 1));
    const yAt = (v) => m.t + ih - (v / scale.max) * ih;

    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "group", "aria-label": o.ariaLabel }, node);
    const defs = el("defs", {}, svg);
    const grad = el("linearGradient", { id: gid, x1: 0, y1: 0, x2: 0, y2: 1 }, defs);
    el("stop", { offset: "0%", class: "grad-top" }, grad);
    el("stop", { offset: "100%", class: "grad-bottom" }, grad);

    for (let v = 0; v <= scale.max + scale.step / 2; v += scale.step) {
      const y = yAt(v);
      el("line", { x1: m.l, x2: W - m.r, y1: y, y2: y, class: v === 0 ? "grid-line base-line" : "grid-line" }, svg);
      const t = el("text", { x: m.l - 8, y: y + 4, "text-anchor": "end", class: "axis-text" }, svg);
      t.textContent = (o.fmtAxis || moneyCompact)(v);
    }

    const pts = data.map((d, i) => [xAt(i), yAt(o.y(d))]);
    const base = yAt(0);
    if (pts.length > 1) {
      const line = pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" ");
      el("path", { d: `${line} L${pts[pts.length - 1][0].toFixed(1)},${base} L${pts[0][0].toFixed(1)},${base} Z`, fill: `url(#${gid})` }, svg);
      el("path", { d: line, class: "line-path" }, svg);
    }

    const every = Math.ceil(data.length / Math.max(1, Math.floor(iw / 56)));
    const colW = iw / data.length;
    data.forEach((d, i) => {
      const [x, y] = pts[i];
      const selected = o.hasSelection && o.isSelected(d);
      const dim = o.hasSelection && !selected;
      const g = el("g", { class: "bar-hit" }, svg);
      el("rect", { x: x - colW / 2, y: m.t, width: colW, height: ih + 6, class: "hit" }, g);
      el("circle", { cx: x, cy: y, r: selected ? 6 : 4.5, class: `pt${selected ? " sel" : ""}${dim ? " dim" : ""}` }, g);
      interactive(g, {
        tooltip: () => o.tooltip(d),
        onSelect: o.onSelect ? () => o.onSelect(d) : null,
        label: o.pointLabel ? o.pointLabel(d) : undefined,
      });
      if (data.length <= 10) {
        const v = el("text", { x, y: y - 11, "text-anchor": "middle", class: "val-text" }, svg);
        v.textContent = (o.fmtValue || moneyCompact)(o.y(d));
      }
      if (i % every === 0 || i === data.length - 1) {
        const t = el("text", { x, y: H - 22, "text-anchor": "middle", class: "axis-text" }, svg);
        t.textContent = o.x(d);
        if (o.x2) {
          const t2 = el("text", { x, y: H - 8, "text-anchor": "middle", class: "axis-text val-muted" }, svg);
          t2.textContent = o.x2(d);
        }
      }
    });
  });
}

// ---------------------------------------------------------------------------
// horizontal bar chart (sorted lists: products, states)
// ---------------------------------------------------------------------------
export function hBarChart(node, o) {
  const data = o.data || [];
  if (!data.length || data.every((d) => !(o.value(d) > 0))) return showEmpty(node, o.emptyText);

  mount(node, () => {
    node.replaceChildren();
    const W = widthOf(node, 260);
    const rowH = o.rowHeight || 28;
    const labelW = Math.min(o.labelWidth || 112, Math.floor(W * 0.38));
    const rightW = o.rightWidth || 92;
    const barW = Math.max(40, W - labelW - rightW - 8);
    const maxV = Math.max(...data.filter((d) => !d.__note).map(o.value), 0) || 1;
    const H = data.length * rowH + 6;
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "group", "aria-label": o.ariaLabel }, node);
    const limit = Math.max(8, Math.floor(labelW / 7));

    data.forEach((d, i) => {
      const y = i * rowH + 3;
      const selected = o.hasSelection && o.isSelected(d);
      const dim = o.hasSelection && !selected;
      const g = el("g", { class: o.onSelect && !d.__static ? "bar-hit" : "bar-static" }, svg);
      el("rect", { x: 0, y, width: W, height: rowH - 2, rx: 6, class: "row-bg" }, g);
      const label = el("text", { x: 4, y: y + rowH / 2 + 3, class: "lbl-text", "font-weight": selected ? 700 : 400 }, g);
      label.textContent = truncate(o.label(d), d.__note ? 40 : limit);
      if (d.__note) {
        // text-only footnote row (e.g. "Other (39)"): no bar, so it cannot dwarf the real categories
        label.setAttribute("class", "lbl-text val-muted");
      } else {
        el("rect", { x: labelW, y: y + 6, width: barW, height: rowH - 14, rx: 4, class: "track" }, g);
        el("rect", { x: labelW, y: y + 6, width: Math.max(2, (o.value(d) / maxV) * barW), height: rowH - 14, rx: 4, class: `bar${dim ? " dim" : ""}` }, g);
      }
      const right = el("text", { x: W - 4, y: y + rowH / 2 + 3, "text-anchor": "end", class: "val-text" }, g);
      const a = el("tspan", {}, right);
      a.textContent = (o.fmtValue || moneyCompact)(o.value(d));
      if (o.rightExtra) {
        const b = el("tspan", { dx: 6, class: "val-muted" }, right);
        b.textContent = o.rightExtra(d);
      }
      interactive(g, {
        tooltip: () => o.tooltip(d),
        onSelect: o.onSelect && !d.__static ? () => o.onSelect(d) : null,
        label: o.rowLabel ? o.rowLabel(d) : undefined,
      });
    });
  });
}

// ---------------------------------------------------------------------------
// column chart (frequency histogram, hours of day)
// ---------------------------------------------------------------------------
export function columnChart(node, o) {
  const data = o.data || [];
  if (!data.length || data.every((d) => !(o.value(d) > 0))) return showEmpty(node, o.emptyText);

  mount(node, () => {
    node.replaceChildren();
    const W = widthOf(node, 260);
    const H = o.height || 240;
    const m = { l: 44, r: 8, t: 22, b: o.xTitle ? 46 : 30 };
    const iw = W - m.l - m.r;
    const ih = H - m.t - m.b;
    const scale = niceScale(Math.max(...data.map(o.value)), 4);
    const band = iw / data.length;
    const barW = Math.min(o.maxBar || 46, band * 0.66);
    const yAt = (v) => m.t + ih - (v / scale.max) * ih;

    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "group", "aria-label": o.ariaLabel }, node);
    for (let v = 0; v <= scale.max + scale.step / 2; v += scale.step) {
      const y = yAt(v);
      el("line", { x1: m.l, x2: W - m.r, y1: y, y2: y, class: v === 0 ? "grid-line base-line" : "grid-line" }, svg);
      const t = el("text", { x: m.l - 6, y: y + 4, "text-anchor": "end", class: "axis-text" }, svg);
      t.textContent = intCompact(v);
    }
    const showValues = barW >= 20;
    const every = o.xEvery || 1;
    data.forEach((d, i) => {
      const cx = m.l + band * i + band / 2;
      const v = o.value(d);
      const g = el("g", { class: "bar-hit" }, svg);
      el("rect", { x: cx - band / 2, y: m.t, width: band, height: ih, class: "hit" }, g);
      el("rect", { x: cx - barW / 2, y: yAt(v), width: barW, height: Math.max(0, m.t + ih - yAt(v)), rx: 3, class: `bar ${o.barClass ? o.barClass(d) : ""}` }, g);
      interactive(g, { tooltip: () => o.tooltip(d), label: o.pointLabel ? o.pointLabel(d) : undefined });
      if (showValues && v > 0) {
        const t = el("text", { x: cx, y: yAt(v) - 6, "text-anchor": "middle", class: "val-text" }, svg);
        t.textContent = (o.fmtValue || intCompact)(v);
      }
      if (i % every === 0) {
        const t = el("text", { x: cx, y: m.t + ih + 16, "text-anchor": "middle", class: "axis-text" }, svg);
        t.textContent = o.label(d);
      }
    });
    if (o.xTitle) {
      const t = el("text", { x: m.l + iw / 2, y: H - 6, "text-anchor": "middle", class: "axis-text val-muted" }, svg);
      t.textContent = o.xTitle;
    }
  });
}

// ---------------------------------------------------------------------------
// donut chart with legend
// ---------------------------------------------------------------------------
export function donutChart(node, o) {
  const data = (o.data || []).filter((d) => o.value(d) > 0);
  if (!data.length) return showEmpty(node, o.emptyText);

  mount(node, () => {
    node.replaceChildren();
    const size = Math.min(widthOf(node, 160), 200);
    const stroke = 26;
    const r = size / 2 - stroke / 2 - 2;
    const C = 2 * Math.PI * r;
    const total = data.reduce((s, d) => s + o.value(d), 0);

    const wrap = document.createElement("div");
    wrap.style.display = "grid";
    wrap.style.justifyItems = "center";
    node.appendChild(wrap);
    const svg = el("svg", { viewBox: `0 0 ${size} ${size}`, width: size, height: size, role: "group", "aria-label": o.ariaLabel }, wrap);
    el("circle", { cx: size / 2, cy: size / 2, r, fill: "none", class: "track-ring", "stroke-width": stroke }, svg);

    let offset = 0;
    data.forEach((d, i) => {
      const len = (o.value(d) / total) * C;
      const gap = data.length > 1 ? Math.min(2, len * 0.25) : 0;
      const seg = el("circle", {
        cx: size / 2, cy: size / 2, r, class: "donut-seg", "stroke-width": stroke,
        "stroke-dasharray": `${Math.max(0, len - gap)} ${C - Math.max(0, len - gap)}`,
        "stroke-dashoffset": -offset,
        transform: `rotate(-90 ${size / 2} ${size / 2})`,
      }, svg);
      seg.style.stroke = `var(--c${(i % 6) + 1})`;
      interactive(seg, { tooltip: () => o.tooltip(d), label: o.itemLabel ? o.itemLabel(d) : undefined });
      offset += len;
    });
    if (o.centerTop) {
      const t = el("text", { x: size / 2, y: size / 2 - 2, "text-anchor": "middle", class: "val-text", "font-size": 17 }, svg);
      t.textContent = o.centerTop;
      const b = el("text", { x: size / 2, y: size / 2 + 15, "text-anchor": "middle", class: "axis-text" }, svg);
      b.textContent = o.centerBottom || "";
    }

    const legend = document.createElement("ul");
    legend.className = "legend";
    legend.style.width = "100%";
    data.forEach((d, i) => {
      const li = document.createElement("li");
      const dot = document.createElement("span");
      dot.className = "dot";
      dot.style.background = `var(--c${(i % 6) + 1})`;
      const name = document.createElement("span");
      name.textContent = o.label(d);
      const pct = document.createElement("span");
      pct.className = "pct";
      pct.textContent = o.legendValue(d);
      li.append(dot, name, pct);
      legend.appendChild(li);
    });
    node.appendChild(legend);
  });
}

// ---------------------------------------------------------------------------
// sparkline (tiny trend line inside KPI cards)
// ---------------------------------------------------------------------------
export function sparkline(node, values) {
  node.replaceChildren();
  if (!values || values.length < 2) return;
  const W = Math.max(node.clientWidth, 60);
  const H = Math.max(node.clientHeight, 28);
  const max = Math.max(...values, 0);
  const min = Math.min(...values);
  const span = max - min || 1;
  const pts = values.map((v, i) => [
    (i * (W - 2)) / (values.length - 1) + 1,
    H - 3 - ((v - min) / span) * (H - 8),
  ]);
  const line = pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" ");
  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, "aria-hidden": "true" }, node);
  el("path", { d: `${line} L${W - 1},${H} L1,${H} Z`, class: "spark-area" }, svg);
  el("path", { d: line, class: "spark-line" }, svg);
}

export { esc };
