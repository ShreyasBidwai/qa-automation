import { defineConfig } from "@playwright/test";

// Deterministic by design (Standards §15): no retries (no flaky-masking),
// auto-waiting assertions instead of sleeps.
export default defineConfig({
  testDir: "./tests",
  timeout: 30_000,
  expect: { timeout: 10_000 },
  retries: 0,
  forbidOnly: true,
  reporter: [["list"]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://frontend:5173",
    trace: "retain-on-failure",
  },
});
