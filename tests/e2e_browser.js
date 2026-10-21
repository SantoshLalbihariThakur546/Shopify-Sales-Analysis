// Optional real-browser test. Setup: npm install playwright && npx playwright install chromium
// Run:   node tests/e2e_browser.js      (BASE_URL defaults to http://127.0.0.1:5000)
const os = require("os");
const { chromium } = require("playwright");
const OUT = os.tmpdir();

const BASE = process.env.BASE_URL || "http://127.0.0.1:5000";
const results = [];
const problems = [];
const check = (name, ok, detail = "") => {
  results.push({ name, ok });
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${ok ? "" : "  -> " + detail}`);
};

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, acceptDownloads: true });
  const page = await ctx.newPage();
  page.on("console", (m) => { if (["error", "warning"].includes(m.type())) problems.push(`console.${m.type()}: ${m.text()}`); });
  page.on("pageerror", (e) => problems.push("pageerror: " + e.message));

  const kpi = (i) => page.locator(".kpi-value").nth(i);
  const waitKpi = async (i, text, timeout = 5000) => {
    try {
      await page.waitForFunction(([idx, txt]) => document.querySelectorAll(".kpi-value")[idx]?.textContent === txt, [i, text], { timeout });
      return true;
    } catch { return false; }
  };
  const kpiText = async (i) => (await kpi(i).textContent());

  // ---------------------------------------------------------------- 1. initial load
  await page.goto(BASE, { waitUntil: "networkidle" });
  check("initial KPI: total sales", await waitKpi(0, "$4,598,961"), await kpiText(0));
  check("initial KPI: orders", (await kpiText(1)) === "7,431");
  check("initial KPI: customers", (await kpiText(2)) === "4,431");
  check("initial KPI: AOV", (await kpiText(3)) === "$618.89");
  check("initial KPI: units", (await kpiText(4)) === "7,534");
  check("initial KPI: repeat share", (await kpiText(5)) === "46.0%");
  check("daily chart has 7 points", (await page.locator("#chart-daily g[role=button]").count()) === 7);
  check("product chart has 14 bars", (await page.locator("#chart-products g[role=button]").count()) === 14);
  check("frequency chart has 5 bars", (await page.locator("#chart-frequency g.bar-hit").count()) === 5);
  check("hourly chart has 24 bars", (await page.locator("#chart-hourly g.bar-hit").count()) === 24);
  check("5 insights rendered", (await page.locator("#insights-list li").count()) === 5);
  check("quality checks rendered", (await page.locator("#quality-list li").count()) === 9);
  check("product table 14 rows + total", (await page.locator("#product-table tbody tr").count()) === 14 && (await page.locator("#product-table tfoot tr").count()) === 1);
  check("top customers 10 rows", (await page.locator("#top-customers tbody tr").count()) === 10);
  check("customer ids masked", (await page.locator("#top-customers tbody tr td:nth-child(2)").first().textContent()).startsWith("•••"));
  check("period pill", (await page.locator("#period-pill").textContent()).includes("18–24 Mar 2025"));
  check("one-week limitation notice visible", await page.locator(".notice").isVisible());

  // ---------------------------------------------------------------- 2. tooltip
  await page.locator("#chart-daily g[role=button]").nth(6).hover();
  const tip = await page.locator("#tooltip");
  check("tooltip shows on hover", await tip.isVisible() && (await tip.textContent()).includes("$752,227.32"), await tip.textContent());
  await page.mouse.move(5, 5);

  // ---------------------------------------------------------------- 3. click product bar -> cross filter
  await page.locator("#chart-products g[role=button]").filter({ hasText: "Running Shoes" }).click();
  check("click bar filters: orders = 2,618", await waitKpi(1, "2,618"), await kpiText(1));
  check("click bar filters: sales", (await kpiText(0)) === "$1,616,946");
  check("chip shown", (await page.locator(".chip").filter({ hasText: "Running Shoes" }).count()) === 1);
  check("URL reflects filter", page.url().includes("product_type=Running+Shoes"), page.url());
  check("bar chart keeps all 14 bars (slicer-style)", (await page.locator("#chart-products g[role=button]").count()) === 14);
  check("unselected bars are dimmed", (await page.locator("#chart-products rect.bar.dim").count()) === 13);
  check("insight adapts to filter", (await page.locator("#insights-list").textContent()).includes("single product type"));

  await page.locator("#chart-products g[role=button]").filter({ hasText: "Sandals" }).click();
  check("second product adds: orders 2,779", await waitKpi(1, "2,779"), await kpiText(1));

  await page.locator(".chip").filter({ hasText: "Running Shoes" }).click();
  check("removing chip: orders 161", await waitKpi(1, "161"), await kpiText(1));

  await page.locator("#reset-btn").click();
  check("reset restores 7,431", await waitKpi(1, "7,431"), await kpiText(1));
  check("no chips after reset", (await page.locator(".chip").count()) === 0);
  check("URL clean after reset", !page.url().includes("?"), page.url());

  // ---------------------------------------------------------------- 4. click day
  await page.locator("#chart-daily g[role=button]").nth(6).click();
  check("click day: sales $752,227", await waitKpi(0, "$752,227"), await kpiText(0));
  check("click day: orders 1,204", (await kpiText(1)) === "1,204");
  check("daily chart still shows 7 days", (await page.locator("#chart-daily g[role=button]").count()) === 7);
  check("date inputs follow", (await page.inputValue("#f-start")) === "2025-03-24" && (await page.inputValue("#f-end")) === "2025-03-24");
  await page.locator("#chart-daily g[role=button]").nth(6).click();
  check("click same day again clears", await waitKpi(1, "7,431"), await kpiText(1));
  // first day (start == data minimum edge case)
  await page.locator("#chart-daily g[role=button]").nth(0).click();
  check("first-day edge: orders 945", await waitKpi(1, "945"), await kpiText(1));
  await page.locator("#chart-daily g[role=button]").nth(0).click();
  check("first-day edge: toggles off", await waitKpi(1, "7,431"), await kpiText(1));

  // ---------------------------------------------------------------- 5. date inputs
  await page.fill("#f-start", "2025-03-20");
  check("date range Mar 20-24: orders 5,396", await waitKpi(1, "5,396"), await kpiText(1));
  await page.fill("#f-end", "2025-03-19"); // earlier than start -> start is pulled back
  await page.waitForTimeout(400);
  check("end before start is corrected", (await page.inputValue("#f-start")) <= (await page.inputValue("#f-end")));
  await page.locator("#reset-btn").click();
  await waitKpi(1, "7,431");

  // ---------------------------------------------------------------- 6. basis toggle
  await page.locator("#basis-toggle button[data-basis=excl_tax]").click();
  check("excl. tax: total sales $4,180,874", await waitKpi(0, "$4,180,874"), await kpiText(0));
  check("excl. tax: AOV $562.63", (await kpiText(3)) === "$562.63", await kpiText(3));
  check("excl. tax label shown", (await page.locator(".kpi-label").first().textContent()).includes("excl. tax"));
  check("URL has basis", page.url().includes("basis=excl_tax"));
  await page.locator("#basis-toggle button[data-basis=incl_tax]").click();
  await waitKpi(0, "$4,598,961");

  // ---------------------------------------------------------------- 7. multi-select dropdowns
  await page.locator("#f-products .ms-btn").click();
  await page.fill("#f-products input[type=search]", "shoes");
  const visible = await page.locator("#f-products .ms-item:visible").count();
  check("product search narrows list to 6 'shoes' types", visible === 6, String(visible));
  await page.locator("#f-products .ms-item:visible").filter({ hasText: "Tennis Shoes" }).locator("input").check();
  await page.locator("#f-products .ms-item:visible").filter({ hasText: "Walking Shoes" }).locator("input").check();
  check("two types: orders 1,585 + 1,099 = 2,684", await waitKpi(1, "2,684"), await kpiText(1));
  check("button shows '2 selected'", (await page.locator("#f-products .ms-text").textContent()) === "2 selected");
  await page.keyboard.press("Escape");
  check("Escape closes dropdown", await page.locator("#f-products .ms-pop").isHidden());
  await page.locator("#reset-btn").click();
  await waitKpi(1, "7,431");

  await page.locator("#f-provinces .ms-btn").click();
  await page.locator("#f-provinces .ms-item").filter({ hasText: "California" }).locator("input").check();
  check("state filter California: orders 869", await waitKpi(1, "869"), await kpiText(1));
  check("state chart shows only California", (await page.locator("#chart-provinces g.bar-static, #chart-provinces g[role=img]").count()) >= 1);
  await page.locator("#reset-btn").click();
  await waitKpi(1, "7,431");

  await page.locator("#f-gateways .ms-btn").click();
  await page.locator("#f-gateways .ms-item").filter({ hasText: "Paypal" }).locator("input").check();
  check("gateway filter PayPal: orders 1,299", await waitKpi(1, "1,299"), await kpiText(1));
  await page.locator("#reset-btn").click();
  await waitKpi(1, "7,431");

  // ---------------------------------------------------------------- 8. reveal ids
  await page.locator("#reveal-ids").check();
  await page.waitForFunction(() => /^\d+$/.test(document.querySelector("#top-customers tbody tr td:nth-child(2)")?.textContent || ""));
  check("reveal IDs shows numeric ids", true);
  await page.locator("#reveal-ids").uncheck();
  await page.waitForFunction(() => (document.querySelector("#top-customers tbody tr td:nth-child(2)")?.textContent || "").startsWith("•"));
  check("hide IDs masks again", true);

  // ---------------------------------------------------------------- 9. table sort
  const firstProduct = () => page.locator("#product-table tbody tr td:first-child").first().textContent();
  check("table default: Running Shoes first", (await firstProduct()) === "Running Shoes");
  await page.locator("#product-table thead button[data-key=product_type]").click();
  check("sort by name asc: Accessories first", (await firstProduct()) === "Accessories", await firstProduct());
  await page.locator("#product-table thead button[data-key=product_type]").click();
  check("sort by name desc: Water Shoes first", (await firstProduct()) === "Water Shoes", await firstProduct());
  await page.locator("#product-table thead button[data-key=units]").click();
  check("sort by units desc: Running Shoes first", (await firstProduct()) === "Running Shoes");

  // ---------------------------------------------------------------- 10. keyboard
  await page.locator("#chart-products g[role=button]").filter({ hasText: "Boots" }).focus();
  check("focus shows tooltip", await page.locator("#tooltip").isVisible());
  await page.keyboard.press("Enter");
  check("Enter on bar filters (Boots = 105 orders)", await waitKpi(1, "105"), await kpiText(1));
  await page.locator("#reset-btn").click();
  await waitKpi(1, "7,431");

  // ---------------------------------------------------------------- 11. export
  await page.locator("#export-btn").click();
  check("export menu opens", await page.locator("#export-pop").isVisible());
  const href = await page.getAttribute("#export-products", "href");
  const csvResp = await page.request.get(BASE + href);
  const csvText = await csvResp.text();
  check("export CSV downloads", csvResp.status() === 200 && csvText.startsWith("Product Type,"), csvText.slice(0, 60));
  check("export CSV has 14 data rows", csvText.trim().split("\n").length === 15);
  await page.mouse.click(5, 300);
  check("click outside closes export menu", await page.locator("#export-pop").isHidden());

  // ---------------------------------------------------------------- 12. deep link
  await page.goto(`${BASE}/?product_type=Sandals&basis=excl_tax&start=2025-03-20&end=2025-03-22&product_type=Not+A+Product`, { waitUntil: "networkidle" });
  await page.waitForTimeout(500);
  const dl = await Promise.all([kpiText(0), kpiText(1), page.inputValue("#f-start"), page.inputValue("#f-end"), page.locator(".chip").count()]);
  check("deep link restores filters (unknown value ignored)", dl[2] === "2025-03-20" && dl[3] === "2025-03-22" && dl[4] === 2, JSON.stringify(dl));
  check("deep link KPIs match pandas (74 orders, $43,593 excl. tax)", dl[0] === "$43,593" && dl[1] === "74", JSON.stringify(dl));

  // ---------------------------------------------------------------- 13. empty state
  await page.goto(`${BASE}/?product_type=Water+Shoes&gateway=manual`, { waitUntil: "networkidle" });
  await page.waitForTimeout(500);
  check("empty selection: orders 0", (await kpiText(1)) === "0", await kpiText(1));
  check("empty selection: AOV $0.00 (no NaN)", (await kpiText(3)) === "$0.00", await kpiText(3));
  check("empty selection: friendly messages", (await page.locator(".empty").count()) >= 4, String(await page.locator(".empty").count()));
  check("empty selection: no-data insight", (await page.locator("#insights-list").textContent()).includes("No orders match"));
  await page.screenshot({ path: `${OUT}/shopify_e2e_empty.png` });

  // ---------------------------------------------------------------- 14. dark theme
  await page.goto(BASE, { waitUntil: "networkidle" });
  await page.locator("#theme-btn").click();
  check("dark theme toggles", (await page.getAttribute("html", "data-theme")) === "dark");
  await page.waitForTimeout(300);
  await page.screenshot({ path: `${OUT}/shopify_e2e_dark.png` });
  await page.reload({ waitUntil: "networkidle" });
  check("dark theme persists after reload", (await page.getAttribute("html", "data-theme")) === "dark");
  await page.locator("#theme-btn").click();

  // ---------------------------------------------------------------- 15. responsive
  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(600);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  check("mobile: no horizontal overflow", overflow <= 1, `overflow ${overflow}px`);
  await page.screenshot({ path: `${OUT}/shopify_e2e_mobile.png`, fullPage: true });
  await page.setViewportSize({ width: 820, height: 1100 });
  await page.waitForTimeout(600);
  const overflowTablet = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  check("tablet: no horizontal overflow", overflowTablet <= 1, `overflow ${overflowTablet}px`);
  await page.screenshot({ path: `${OUT}/shopify_e2e_tablet.png`, fullPage: true });
  await page.setViewportSize({ width: 1440, height: 900 });

  // ---------------------------------------------------------------- 16. backend failure
  const page2 = await ctx.newPage();
  await page2.route("**/api/dashboard**", (route) => route.abort());
  await page2.goto(BASE, { waitUntil: "networkidle" });
  await page2.waitForTimeout(500);
  const banner = page2.locator("#error-banner");
  check("backend failure shows friendly error banner", (await banner.isVisible()) && (await banner.textContent()).includes("Cannot reach the backend"), await banner.textContent());
  await page2.unroute("**/api/dashboard**");
  await page2.locator("#error-banner button").click();
  await page2.waitForFunction(() => document.querySelectorAll(".kpi-value")[1]?.textContent === "7,431", null, { timeout: 5000 });
  check("'Try again' recovers", await page2.locator("#error-banner").isHidden());

  const page3 = await ctx.newPage();
  await page3.route("**/api/dashboard**", (route) => route.fulfill({ status: 400, contentType: "application/json", body: JSON.stringify({ error: "'start' must be a date in YYYY-MM-DD format." }) }));
  await page3.goto(BASE, { waitUntil: "networkidle" });
  await page3.waitForTimeout(400);
  check("API 400 message is shown to the user", (await page3.locator("#error-banner").textContent()).includes("YYYY-MM-DD"));

  // ---------------------------------------------------------------- summary
  const failed = results.filter((r) => !r.ok);
  const realProblems = problems.filter((p) => !p.includes("net::ERR_FAILED") && !p.includes("Failed to load resource") && !p.includes("400 (BAD REQUEST)") && !p.includes("Cannot reach"));
  console.log("\nCONSOLE/PAGE PROBLEMS:", realProblems.length ? JSON.stringify(realProblems, null, 1) : "none");
  console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
  await browser.close();
  process.exit(failed.length || realProblems.length ? 1 : 0);
})().catch((e) => { console.error("SCRIPT ERROR:", e); process.exit(2); });
