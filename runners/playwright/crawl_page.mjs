// Stack-agnostic single-page crawl driver for the FrontendCrawler (T4.2).
//
// Reads a JSON config from STDIN: { url, origin, waitMs, auth? } — credentials
// (if any) arrive over stdin, never argv. Launches a browser, optionally logs
// in, navigates to `url`, intercepts same-origin xhr/fetch calls, reads the
// rendered DOM, and prints ONE page snapshot as JSON to stdout. Opens and closes
// its own browser, so no process/browser leaks (Standards §11). The Python
// PlaywrightPageFetcher invokes this once per page; the BFS/caps live in Python.

import { chromium } from "@playwright/test";

function readStdin() {
  return new Promise((resolve) => {
    let data = "";
    process.stdin.setEncoding("utf8");
    process.stdin.on("data", (chunk) => (data += chunk));
    process.stdin.on("end", () => resolve(data));
  });
}

const input = JSON.parse((await readStdin()) || "{}");
const { url, origin, waitMs = 1500, auth = null } = input;

const browser = await chromium.launch();
const calls = [];
try {
  const context = await browser.newContext();
  const page = await context.newPage();

  // Capture which BACKEND calls the page makes (xhr/fetch), same-origin only.
  page.on("request", (req) => {
    const rt = req.resourceType();
    if (rt !== "xhr" && rt !== "fetch") return;
    try {
      if (new URL(req.url()).origin === new URL(origin).origin) {
        calls.push({ method: req.method().toUpperCase(), url: req.url(), resource_type: rt });
      }
    } catch {
      /* ignore unparseable URLs */
    }
  });

  if (auth) {
    await page.goto(auth.login_url, { waitUntil: "domcontentloaded" });
    await page.fill(auth.username_selector, auth.username);
    await page.fill(auth.password_selector, auth.password);
    await Promise.all([
      page.waitForLoadState("networkidle").catch(() => {}),
      page.click(auth.submit_selector),
    ]);
  }

  await page.goto(url, { waitUntil: "domcontentloaded" });
  await page.waitForLoadState("networkidle").catch(() => {});
  await page.waitForTimeout(waitMs); // let client-side fetches fire

  const dom = await page.evaluate(() => {
    const abs = (h) => {
      try {
        return new URL(h, document.baseURI).href;
      } catch {
        return null;
      }
    };
    const links = Array.from(document.querySelectorAll("a[href]"))
      .map((a) => abs(a.getAttribute("href")))
      .filter(Boolean);
    const forms = Array.from(document.querySelectorAll("form")).map((f) => ({
      action: f.getAttribute("action") ? abs(f.getAttribute("action")) : null,
      method: (f.getAttribute("method") || "GET").toUpperCase(),
      fields: Array.from(f.querySelectorAll("input,select,textarea"))
        .map((el) => ({
          name: el.getAttribute("name") || "",
          type: el.getAttribute("type") || el.tagName.toLowerCase(),
          required: el.hasAttribute("required"),
        }))
        .filter((x) => x.name),
    }));
    const elements = Array.from(document.querySelectorAll("button, a[href]")).map((el) => ({
      tag: el.tagName.toLowerCase(),
      text: (el.textContent || "").trim().slice(0, 120),
    }));
    return { title: document.title, links, forms, elements };
  });

  process.stdout.write(
    JSON.stringify({
      url: page.url(),
      title: dom.title,
      links: dom.links,
      forms: dom.forms,
      elements: dom.elements,
      network: calls,
    }),
  );
} finally {
  await browser.close();
}
