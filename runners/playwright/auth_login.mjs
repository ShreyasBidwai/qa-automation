// Interim manual-OTP login driver for ManualOtpStrategy (T4.2a).
//
// Protocol (one JSON object per line) with the Python PlaywrightLoginBrowser:
//   <- {login_url, username, password, *_selector, timeout_ms}   (first stdin line)
//   -> {"event":"otp_required","channel":...}   (only if a challenge appears)
//   <- {"code":"123456"}                          (the tester's code, from stdin)
//   -> {"event":"done","storageState":{...},"challenge":"none|otp","channel":...,
//       "success":true}
//
// Credentials arrive over stdin (never argv). OTP is CONFIGURED, never cracked:
// the code is supplied by the operator and entered here. Opens/closes its own
// browser, so nothing leaks. Reuses the T4.1 pinned Playwright image.

import { chromium } from "@playwright/test";
import { createInterface } from "node:readline";

const rl = createInterface({ input: process.stdin });
const lines = rl[Symbol.asyncIterator]();
const nextLine = async () => {
  const { value } = await lines.next();
  return value ? JSON.parse(value) : null;
};
const emit = (obj) => process.stdout.write(JSON.stringify(obj) + "\n");

const cfg = await nextLine();
const timeout = cfg.timeout_ms || 180000;

const browser = await chromium.launch();
try {
  const context = await browser.newContext();
  const page = await context.newPage();
  page.setDefaultTimeout(timeout);

  await page.goto(cfg.login_url, { waitUntil: "domcontentloaded" });
  await page.fill(cfg.username_selector, cfg.username);
  await page.fill(cfg.password_selector, cfg.password);
  await page.click(cfg.submit_selector);
  await page.waitForLoadState("networkidle").catch(() => {});

  let challenge = "none";
  let channel = null;
  const otp = page.locator(cfg.otp_selector).first();
  if (await otp.count()) {
    challenge = "otp";
    emit({ event: "otp_required", channel });
    const reply = await nextLine();
    await otp.fill(String(reply && reply.code ? reply.code : ""));
    await page.click(cfg.otp_submit_selector);
    await page.waitForLoadState("networkidle").catch(() => {});
  }

  let success = true;
  if (cfg.success_selector) {
    success = (await page.locator(cfg.success_selector).count()) > 0;
  }

  const storageState = await context.storageState();
  emit({ event: "done", storageState, challenge, channel, success });
} catch (err) {
  emit({ event: "done", storageState: {}, challenge: "none", channel: null, success: false });
  process.stderr.write(String(err && err.message ? err.message : err) + "\n");
} finally {
  await browser.close();
}
