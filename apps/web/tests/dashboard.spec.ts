import { expect, test, type Page } from "@playwright/test";

async function login(page: Page, role: "owner" | "viewer" = "owner") {
  await page.goto("/login");
  await page.getByRole("button", { name: role === "owner" ? "Continue as demo owner" : "Continue as viewer (read-only)", exact: true }).click();
  await expect(page).toHaveURL(/\/overview$/);
  await expect(page.getByRole("heading", { name: "Predict early. Spend smarter." })).toBeVisible();
}

test("all dashboard screens render against the local API", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await login(page);
  await expect(page.getByText("Month-end forecast", { exact: true })).toBeVisible();
  await page.screenshot({ path: "../../artifacts/phase4/overview-desktop.png", fullPage: true });
  for (const [url, heading] of [
    ["/predictions", "Predictions"], ["/anomalies", "Anomalies"], ["/decisions", "Decision Lab"],
    ["/usage", "Usage Explorer"], ["/evaluation", "Evaluation"], ["/settings", "Settings"],
  ]) {
    await page.goto(url);
    await expect(page.getByRole("heading", { name: heading, exact: true })).toBeVisible();
    await expect(page.getByText("Cannot reach the TokenGuard API.", { exact: false })).toHaveCount(0);
  }
  await page.goto("/evaluation");
  await page.getByRole("tab", { name: "Anomalies", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Test events" })).toBeVisible();
  await page.getByRole("tab", { name: "Safe cache & simulator" }).click();
  await expect(page.getByRole("heading", { name: "Similarity threshold sweep" })).toBeVisible();
  await page.getByRole("link", { name: "Read the full model card" }).click();
  await expect(page.getByRole("heading", { name: "Model card", exact: true })).toBeVisible();
  expect(errors).toEqual([]);
});

test("viewer can inspect scenarios but cannot change settings or run forecasts", async ({ page }) => {
  await login(page, "viewer");
  await page.goto("/predictions");
  await expect(page.getByRole("button", { name: "Run forecast", exact: true })).toBeDisabled();
  await page.goto("/settings");
  await expect(page.getByLabel("Monthly budget (MYR)")).toBeDisabled();
  await page.goto("/decisions");
  await expect(page.getByRole("button", { name: "Generate recommendation" })).toBeDisabled();
  await expect(page.getByRole("heading", { name: "Assumptions", exact: true })).toBeVisible();
});

test("mobile navigation, evaluation tabs and usage export work", async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 800 });
  await login(page);
  await page.getByRole("button", { name: "Open navigation" }).click();
  await page.getByRole("link", { name: "Evaluation", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Evaluation", exact: true })).toBeVisible();
  await page.getByRole("tab", { name: "Safe cache & simulator" }).click();
  await expect(page.getByRole("heading", { name: "Similarity threshold sweep" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: "../../artifacts/phase4/evaluation-mobile.png", fullPage: true });
  await page.goto("/usage");
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export CSV (aggregates)" }).click();
  expect((await download).suggestedFilename()).toMatch(/^tokenguard-usage-.*\.csv$/);
});

test("chat identifies mock responses and recovers from connection failure", async ({ page }) => {
  await page.route("**/api/v1/chat/session", (route) => route.abort());
  await page.goto("/demo/chat");
  await expect(page.getByRole("button", { name: "Retry chat connection" })).toBeVisible();
  await page.unroute("**/api/v1/chat/session");
  await page.getByRole("button", { name: "Retry chat connection" }).click();
  await page.getByRole("button", { name: "Is my order ready?", exact: true }).click();
  await expect(page.getByTestId("chat-meta")).toContainText("mock provider");
  await expect(page.getByTestId("chat-meta")).toContainText("Mock response");
  await expect(page.getByTestId("chat-meta")).not.toContainText("Anthropic call");
});

test("failed scenario request shows a retryable error", async ({ page }) => {
  await login(page);
  await page.route("**/api/v1/scenarios/compare", (route) => route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ message: "Unavailable" }) }));
  await page.goto("/decisions");
  await expect(page.getByRole("button", { name: "Retry", exact: true })).toBeVisible();
  await page.unroute("**/api/v1/scenarios/compare");
  await page.getByRole("button", { name: "Retry", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Assumptions", exact: true })).toBeVisible();
});


test("owner simulates, approves FAQ caching, verifies a hit and disables it", async ({ page }) => {
  test.setTimeout(75_000);
  await login(page);
  const token = await page.evaluate(() => localStorage.getItem("tg_dev_token"));
  const headers = { Authorization: `Bearer ${token}` };
  const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
  const policiesResponse = await page.request.get(`${apiBase}/api/v1/policies`, { headers });
  const original = (await policiesResponse.json()).items as { id: string; enabled: boolean }[];
  test.skip(original.some((p) => p.enabled), "Activation smoke check needs initially disabled demo policies.");
  try {
    await page.goto("/decisions");
    await expect(page.getByRole("heading", { name: "Assumptions", exact: true })).toBeVisible();
    const slider = page.getByRole("slider", { name: "Safe hit rate" });
    const before = await slider.getAttribute("aria-valuenow");
    await slider.focus();
    await slider.press("ArrowRight");
    await expect(slider).not.toHaveAttribute("aria-valuenow", before!);
    await page.getByRole("button", { name: "Reset", exact: true }).click();
    await page.getByRole("button", { name: "Generate recommendation" }).click();
    await page.getByRole("button", { name: "Approve & enable", exact: true }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByText("Quality risks", { exact: true })).toBeVisible();
    await dialog.getByRole("button", { name: "Approve & enable", exact: true }).click();
    await expect(dialog).not.toBeVisible();
    await expect(page.getByRole("button", { name: "Disable", exact: true }).first()).toBeVisible();
    await page.screenshot({ path: "../../artifacts/phase4/decision-lab-desktop.png", fullPage: true });
    await page.goto("/demo/chat");
    await page.getByRole("button", { name: "What time do you open?", exact: true }).click();
    await expect(page.getByTestId("chat-meta").first()).toContainText("Safe cache hit");
    await page.getByRole("button", { name: "Is my order ready?", exact: true }).click();
    await expect(page.getByTestId("chat-meta").last()).toContainText("Mock response");
    await page.goto("/decisions");
    const disable = page.getByRole("button", { name: "Disable", exact: true });
    await expect(disable.first()).toBeVisible();
    while (await disable.count()) {
      const count = await disable.count();
      await disable.first().click();
      await expect(disable).toHaveCount(count - 1);
    }
    await page.goto("/demo/chat");
    await page.getByRole("button", { name: "What time do you open?", exact: true }).click();
    await expect(page.getByTestId("chat-meta").first()).toContainText("Mock response");
  } finally {
    // Restore initially disabled policies even if a UI assertion fails; retain the audit trail.
    const current = await page.request.get(`${apiBase}/api/v1/policies`, { headers });
    for (const p of (await current.json()).items as { id: string; enabled: boolean }[]) {
      if (p.enabled && original.some((old) => old.id === p.id && !old.enabled)) {
        await page.request.post(`${apiBase}/api/v1/policies/${p.id}/disable`, { headers });
      }
    }
  }
});


test("all dashboard screens fit a 360px viewport", async ({ page }) => {
  test.setTimeout(75_000);
  await page.setViewportSize({ width: 360, height: 800 });
  await login(page);
  for (const url of ["/overview", "/predictions", "/anomalies", "/decisions", "/usage", "/evaluation", "/settings", "/demo/chat"]) {
    await page.goto(url);
    await expect(page.locator("main")).toBeVisible();
    await expect.poll(() => page.locator('[aria-busy="true"]').count()).toBe(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), url).toBe(true);
  }
});

test("owner budget changes persist and the original budget is restored", async ({ page }) => {
  await login(page);
  await page.goto("/settings");
  const budget = page.getByLabel("Monthly budget (MYR)");
  await expect(budget).toHaveValue(/\d/);
  const original = await budget.inputValue();
  try {
    await budget.fill(String(Number(original) + 1));
    await page.getByRole("button", { name: "Save", exact: true }).click();
    await expect(page.getByText("Budget saved. Re-run the forecast to update risk.", { exact: true })).toBeVisible();
    await page.reload();
    await expect(budget).toHaveValue(String(Number(original) + 1));
  } finally {
    await budget.fill(original);
    const restored = page.waitForResponse((r) => r.url().endsWith("/api/v1/settings/workspace") && r.request().method() === "PATCH");
    await page.getByRole("button", { name: "Save", exact: true }).click();
    expect((await restored).ok()).toBe(true);
    await page.reload();
    await expect(budget).toHaveValue(original);
  }
});
