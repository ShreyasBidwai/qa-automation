import { expect, test } from "@playwright/test";

test("system status page reports the backend as healthy", async ({ page }) => {
  await page.goto("/");

  // The page must render.
  await expect(
    page.getByRole("heading", { name: "System status" }),
  ).toBeVisible();

  // Backend health is fetched live (proxied to the backend) and rendered as a
  // badge. Playwright auto-waits for it — no sleeps (Standards §15). `exact`
  // avoids matching the "All systems operational" overall badge as a substring.
  await expect(page.getByText("Operational", { exact: true })).toBeVisible();
  await expect(page.getByText("All systems operational")).toBeVisible();
});
