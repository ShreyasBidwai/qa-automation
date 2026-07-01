// Stack-agnostic single-page crawl driver for the FrontendCrawler (T4.2).
//
// Reads a JSON config from STDIN: { url, origin, waitMs, storageState?, interact?,
// maxInteractions? } — credentials (if any) arrive over stdin, never argv. Launches
// a browser, optionally logs in, navigates to `url`, intercepts same-origin xhr/fetch
// calls, reads the rendered DOM, optionally DRIVES a few safe interactions to surface
// client-triggered endpoints, and prints ONE page snapshot as JSON to stdout. Opens
// and closes its own browser, so no process/browser leaks (Standards §11). The Python
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
const {
  url,
  origin,
  waitMs = 1500,
  storageState = null,
  interact = true,
  maxInteractions = 5,
} = input;

// SAFETY denylist: interaction crawling clicks in-page controls to observe more
// endpoints, but must NEVER trigger a mutating/destructive action. A control whose
// accessible text matches this, OR that submits a form, is skipped (see driveSafely).
const DESTRUCTIVE =
  "\\b(delete|remove|destroy|drop|clear|reset|pay|buy|purchase|checkout|order|" +
  "place\\s?order|submit|save|update|create|add|confirm|apply|logout|log\\s?out|" +
  "sign\\s?out|unsubscribe|subscribe|cancel|deactivate|disable|archive|send|" +
  "publish|transfer|withdraw|deposit|approve|reject|accept|decline)\\b";

/**
 * Click up to `max` SAFE controls to surface endpoints that only fire on interaction
 * (tabs, filters, "load more"). Safe = a <button>/[role=button]/[role=tab] that is
 * visible + enabled, is NOT a submit/reset, is NOT inside a <form> (so no submission),
 * and whose text doesn't match the destructive denylist. Best-effort: a click that
 * fails or navigates is swallowed; the interceptor keeps accumulating calls.
 */
async function driveSafely(page, max, denySource) {
  const handles = await page.$$("button, [role=button], [role=tab]");
  let done = 0;
  for (const handle of handles) {
    if (done >= max) break;
    try {
      const safe = await handle.evaluate((el, deny) => {
        const text = (el.textContent || el.getAttribute("aria-label") || "").trim();
        if (!text || new RegExp(deny, "i").test(text)) return false;
        const type = (el.getAttribute("type") || "").toLowerCase();
        if (el.tagName === "BUTTON" && (type === "submit" || type === "reset"))
          return false;
        if (el.closest("form")) return false; // never submit/mutate a form
        if (el.hasAttribute("disabled") || el.getAttribute("aria-disabled") === "true")
          return false;
        const rect = el.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0; // visible
      }, denySource);
      if (!safe) continue;
      await handle.click({ timeout: 2000, noWaitAfter: true });
      await page.waitForLoadState("networkidle", { timeout: 2000 }).catch(() => {});
      done += 1;
    } catch {
      /* a failed/navigating interaction is skipped — keep going */
    }
  }
  return done;
}

const browser = await chromium.launch();
const calls = [];
try {
  // Replay the logged-in session captured once by the AuthStrategy (T4.2a);
  // null → a fresh, unauthenticated context. Login is NOT done here.
  const context = await browser.newContext(storageState ? { storageState } : {});
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

  await page.goto(url, { waitUntil: "domcontentloaded" });
  await page.waitForLoadState("networkidle").catch(() => {});
  await page.waitForTimeout(waitMs); // let client-side fetches fire

  // Anchor the snapshot to the page we loaded (before any interaction can navigate).
  const pageUrl = page.url();

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

  // Optionally drive a few SAFE interactions to observe endpoints that only fire on
  // click (tabs/filters/"load more"); the interceptor keeps accumulating `calls`.
  let interactions = 0;
  if (interact && maxInteractions > 0) {
    interactions = await driveSafely(page, maxInteractions, DESTRUCTIVE);
    await page.waitForTimeout(300); // let the last interaction's fetches settle
  }

  // A screenshot of the rendered page (base64 PNG): the operator sees what the
  // crawler saw, and the bytes are stored per-project. Best-effort — a capture
  // failure must not lose the page snapshot, so it degrades to null.
  let screenshot = null;
  try {
    screenshot = (await page.screenshot({ type: "png" })).toString("base64");
  } catch {
    /* keep the snapshot even if the shot fails */
  }

  process.stdout.write(
    JSON.stringify({
      url: pageUrl,
      title: dom.title,
      links: dom.links,
      forms: dom.forms,
      elements: dom.elements,
      network: calls,
      screenshot,
      interactions,
    }),
  );
} finally {
  await browser.close();
}
