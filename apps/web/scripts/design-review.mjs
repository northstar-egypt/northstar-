/** Capture the actual screens with invented API rows. This is visual QA, not backend integration coverage. */
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { fixture } from "./design-fixtures.mjs";
const { firefox, chromium } = await import(process.env.NORTHSTAR_PLAYWRIGHT ? pathToFileURL(process.env.NORTHSTAR_PLAYWRIGHT).href : "playwright");
const base = process.env.DESIGN_BASE_URL || "http://localhost:3000";
const output = path.resolve(process.env.DESIGN_OUTPUT || ".next/design-review");
const phase = process.env.DESIGN_PHASE || "after";
const printOnly = process.env.DESIGN_PRINT_ONLY === "1";
const checksOnly = process.env.DESIGN_CHECKS_ONLY === "1" || printOnly;
const screens = [
  ["home", "/", null], ["login", "/login", null], ["coach", "/dashboard", "coach"],
  ["add-player", "/players/new", "coach"], ["profile", "/players/design-1", "coach"],
  ["log-measurement", "/players/design-1", "coach"],
  ["scout", "/scout", "scout"], ["search", "/search", "scout"],
  ["compare", "/compare?players=design-1,design-2", "scout"], ["gaps", "/gaps", "scout"],
  ["oversight", "/oversight", "federation"], ["integrity", "/integrity", "federation"],
  ["report", "/players/design-1/report", "scout"],
];

async function routeFixtures(page, role, state = "normal") {
  await page.route("http://localhost:8000/**", async route => {
    if (route.request().method() === "OPTIONS") return route.fulfill({ status: 204, headers: cors });
    const url = new URL(route.request().url());
    if (state === "loading" && url.pathname === "/home/scout") await new Promise(resolve => setTimeout(resolve, 1500));
    if (url.pathname === "/me" && !role) return route.fulfill({ status: 401, headers: cors, json: { detail: "Signed out" } });
    if (state === "error" && !["/me", "/dev/identities"].includes(url.pathname) && !url.pathname.startsWith("/health")) return route.fulfill({ status: 503, headers: cors, json: { detail: "Visual review: service temporarily unavailable" } });
    const body = fixture(url.pathname + url.search, role, state);
    return route.fulfill({ status: body === null ? 404 : 200, headers: cors, json: body ?? { detail: "Not in this visual fixture" } });
  });
}
const cors = { "access-control-allow-origin": new URL(base).origin, "access-control-allow-credentials": "true", "access-control-allow-headers": "content-type", "access-control-allow-methods": "GET,POST,OPTIONS" };

async function capture() {
  await fs.mkdir(output, { recursive: true });
  const browser = await firefox.launch();
  const results = checksOnly ? JSON.parse(await fs.readFile(path.join(output, `${phase}-results.json`), "utf8")) : [];
  try {
    for (const width of checksOnly ? [] : [360, 1280]) for (const dir of ["ltr", "rtl"]) for (const [name, route, role] of screens) {
      const context = await browser.newContext({ viewport: { width, height: 900 }, reducedMotion: "reduce" });
      await context.addInitScript(direction => { localStorage.setItem("northstar-layout", direction); document.documentElement?.setAttribute("dir", direction); }, dir);
      const page = await context.newPage();
      const errors = [];
      page.on("pageerror", error => { if (!String(error.stack).includes("next-devtools")) errors.push(error.message); });
      await routeFixtures(page, role);
      await page.goto(base + route, { waitUntil: "networkidle", timeout: 120000 });
      if (name === "report") await page.getByRole("heading", { name: "Against 32 Invented Review League midfielders" }).waitFor();
      if (name === "log-measurement") await page.getByRole("button", { name: "Log measurement", exact: true }).click();
      await page.waitForTimeout(300);
      await page.evaluate(direction => document.documentElement.dir = direction, dir);
      await page.screenshot({ path: path.join(output, `${phase}-${name}-${width}-${dir}.png`), fullPage: true });
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1);
      const item = { name, width, dir, overflow, errors };
      results.push(item);
      console.log(JSON.stringify(item));
      assert.deepEqual(errors, [], `${name} raised a JavaScript error`);
      await context.close();
    }
    if (phase === "after") {
      assert.equal(results.filter(r => r.overflow).length, 0, "A screen overflows the viewport");
      assert.deepEqual(results.flatMap(r => r.errors), [], "A screen raised a JavaScript error");
      if (!printOnly) {
      const context = await browser.newContext({ viewport: { width: 360, height: 900 } });
      const page = await context.newPage();
      await routeFixtures(page, "scout");
      await page.goto(base + "/scout", { waitUntil: "networkidle" });
      const toggle = page.getByRole("button", { name: "Arabic right-to-left layout" });
      await toggle.click();
      assert.equal(await page.locator("html").getAttribute("dir"), "rtl");
      await page.reload({ waitUntil: "networkidle" });
      assert.equal(await page.locator("html").getAttribute("dir"), "rtl");
      await page.keyboard.press("Tab");
      assert.equal(await page.evaluate(() => document.activeElement.textContent), "Skip to content");
      assert.notEqual(await page.evaluate(() => getComputedStyle(document.activeElement).outlineStyle), "none");
      await page.keyboard.press("Enter");
      assert.equal(await page.evaluate(() => document.activeElement.id), "main-content");
      await context.close();
      for (const state of ["empty", "error"]) {
        const context = await browser.newContext({ viewport: { width: 360, height: 900 } });
        const page = await context.newPage();
        await routeFixtures(page, "scout", state);
        await page.goto(base + "/scout", { waitUntil: "networkidle" });
        await page.screenshot({ path: path.join(output, `${phase}-${state}-360.png`), fullPage: true });
        assert.ok(await page.getByText(state === "empty" ? "Nothing saved yet." : "Could not load your home", { exact: false }).count());
        await context.close();
      }
      for (const [state, route] of [["missing", "/players/design-1"], ["insufficient", "/players/design-1/report"], ["loading", "/scout"]]) {
        const context = await browser.newContext({ viewport: { width: 360, height: 900 } });
        const page = await context.newPage();
        const errors = [];
        page.on("pageerror", error => errors.push(error.message));
        await routeFixtures(page, "scout", state);
        await page.goto(base + route, { waitUntil: state === "loading" ? "domcontentloaded" : "networkidle" });
        if (state === "loading") await page.getByRole("status", { name: "Loading", exact: true }).waitFor();
        if (state === "insufficient") {
          assert.equal(await page.getByRole("button", { name: "Print / Save PDF" }).count(), 0);
          await page.getByText("Not enough minutes to grade.", { exact: true }).waitFor({ state: "visible", timeout: 120000 });
        }
        await page.screenshot({ path: path.join(output, `${phase}-${state}-360.png`), fullPage: true });
        assert.deepEqual(errors, []);
        await context.close();
      }
      const tabsContext = await browser.newContext();
      const tabsPage = await tabsContext.newPage();
      await routeFixtures(tabsPage, "scout");
      await tabsPage.goto(base + "/gaps", { waitUntil: "networkidle" });
      await tabsPage.getByRole("tab", { name: "A club", exact: true }).focus();
      await tabsPage.keyboard.press("End");
      assert.equal(await tabsPage.getByRole("tab", { name: "The national team", exact: true }).getAttribute("aria-selected"), "true");
      assert.equal(await tabsPage.getByRole("tabpanel").getAttribute("id"), "national-analysis");
      await tabsContext.close();
      for (const [name, route, role] of [["coach", "/dashboard", "coach"], ["profile", "/players/design-1", "coach"], ["search", "/search", "scout"], ["oversight", "/oversight", "federation"], ["integrity", "/integrity", "federation"]]) {
        const context = await browser.newContext({ viewport: { width: 360, height: 900 } });
        const page = await context.newPage();
        const errors = [];
        page.on("pageerror", error => errors.push(error.message));
        await routeFixtures(page, role, "error");
        await page.goto(base + route, { waitUntil: "networkidle" });
        await page.getByRole("button", { name: "Try again", exact: true }).waitFor({ timeout: 120000 });
        await page.screenshot({ path: path.join(output, `${phase}-${name}-error-360.png`), fullPage: true });
        await page.unroute("http://localhost:8000/**");
        await routeFixtures(page, role);
        await page.getByRole("button", { name: "Try again", exact: true }).click();
        await page.getByRole("button", { name: "Try again", exact: true }).waitFor({ state: "hidden", timeout: 120000 });
        await page.locator("main h1").waitFor({ timeout: 120000 });
        if (name === "coach" || name === "search") await page.getByText("Omar Design Example", { exact: true }).first().waitFor({ timeout: 120000 });
        assert.deepEqual(errors, [], `${name} did not recover from a failed request`);
        await context.close();
      }
      }
      const printBrowser = await chromium.launch();
      try {
        const page = await printBrowser.newPage();
        await routeFixtures(page, "scout");
        await page.goto(base + "/players/design-1/report", { waitUntil: "networkidle" });
        await page.getByRole("heading", { name: "Against 32 Invented Review League midfielders" }).waitFor({ timeout: 120000 });
        await page.emulateMedia({ media: "print" });
        assert.equal(await page.locator(".app-navigation").isVisible(), false);
        assert.equal(await page.locator(".report-print-footer").isVisible(), true);
        assert.equal(await page.locator("html").evaluate(element => getComputedStyle(element).colorScheme), "light");
        assert.equal(await page.locator(".scouting-report svg").first().evaluate(element => getComputedStyle(element).filter), "none");
        let printTimeout;
        try {
          await Promise.race([
            page.pdf({ path: path.join(output, "scouting-report-synthetic.pdf"), printBackground: true, preferCSSPageSize: true }),
            new Promise((_, reject) => { printTimeout = setTimeout(() => reject(new Error("PDF rendering exceeded 30 seconds")), 30000); }),
          ]);
        } finally { clearTimeout(printTimeout); }
        await page.screenshot({ path: path.join(output, "report-print.png"), fullPage: true });
      } finally { await printBrowser.close(); }
    }
  } finally {
    await browser.close();
    await fs.writeFile(path.join(output, `${phase}-results.json`), JSON.stringify(results, null, 2));
  }
}
capture().catch(error => { console.error(error); process.exitCode = 1; });
