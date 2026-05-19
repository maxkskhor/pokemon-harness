import { test, expect } from "@playwright/test";
import { rmSync } from "node:fs";
import { resolve } from "node:path";

test("pokemon harness UI loads and shows connection status", async ({ page }) => {
  const errors = [];
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  page.on("pageerror", (error) => errors.push(error.message));

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("http://127.0.0.1:5173/", { waitUntil: "domcontentloaded" });

  await expect(page.getByRole("heading", { name: "Pokemon Harness" })).toBeVisible();
  await expect(page.getByText("WebSocket")).toBeVisible();
  expect(errors).toEqual([]);
});

test("pokemon harness UI shows game screen when run is active", async ({ page }) => {
  const runId = `smoke-${Date.now()}`;
  const errors = [];
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  page.on("pageerror", (error) => errors.push(error.message));

  try {
    await page.setViewportSize({ width: 1440, height: 900 });

    // Start a run via API (agent controls start runs; UI no longer has a Start Run button)
    await page.request.post("http://127.0.0.1:8000/api/run/start", {
      data: { run_id: runId },
    });

    await page.goto("http://127.0.0.1:5173/", { waitUntil: "domcontentloaded" });
    await expect(page.locator("img.game-screen")).toBeVisible({ timeout: 5000 });

    const screenBox = await page.locator(".screen-wrap").boundingBox();
    expect(screenBox).not.toBeNull();
    expect(screenBox.width).toBeGreaterThan(500);
    expect(screenBox.height).toBeGreaterThan(500);

    await expect(page.locator(".state-grid")).toContainText("Frame");
    expect(errors).toEqual([]);
  } finally {
    await page.request.post("http://127.0.0.1:8000/api/run/stop").catch(() => {});
    rmSync(resolve("..", "runs", runId), { recursive: true, force: true });
    rmSync(resolve("..", "states", runId), { recursive: true, force: true });
  }
});

test("trace filter checkboxes toggle correctly including screenshots", async ({ page }) => {
  const errors = [];
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("http://127.0.0.1:5173/", { waitUntil: "domcontentloaded" });

  // All filter labels should be visible
  await expect(page.getByLabel("Trace event filters")).toBeVisible();
  for (const label of ["decision", "llm", "action", "warning", "error", "screenshots"]) {
    await expect(page.getByLabel("Trace event filters").getByText(label, { exact: false })).toBeVisible();
  }

  // Screenshots toggle starts checked; unchecking it should persist
  const screenshotsLabel = page.getByLabel("Trace event filters").locator("label").filter({ hasText: "screenshots" });
  const screenshotsCheckbox = screenshotsLabel.locator("input");
  await expect(screenshotsCheckbox).toBeChecked();
  await screenshotsLabel.click();
  await expect(screenshotsCheckbox).not.toBeChecked();

  expect(errors).toEqual([]);
});

test("status grid shows agent fields and omits ROM and Symbols", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("http://127.0.0.1:5173/", { waitUntil: "domcontentloaded" });

  const grid = page.locator(".state-grid");
  await expect(grid).toBeVisible();

  // Agent-relevant fields must be present
  for (const label of ["Frame", "Map", "X/Y", "Party", "Speed"]) {
    await expect(grid.getByText(label, { exact: true })).toBeVisible();
  }

  // Scaffold-only fields must be absent
  await expect(grid.getByText("ROM", { exact: true })).not.toBeVisible();
  await expect(grid.getByText("Symbols", { exact: true })).not.toBeVisible();
});

test("paused speed button tooltip explains it does not stop the agent", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("http://127.0.0.1:5173/", { waitUntil: "domcontentloaded" });

  const tooltip = await page.getByRole("button", { name: /paused/ }).getAttribute("title");
  expect(tooltip).toBeTruthy();
  expect(tooltip.toLowerCase()).toContain("agent");
});

test("screenshots toggle actually hides trace thumbnails when a run is active", async ({ page }) => {
  const runId = `smoke-thumb-${Date.now()}`;
  try {
    await page.setViewportSize({ width: 1440, height: 900 });

    await page.request.post("http://127.0.0.1:8000/api/run/start", { data: { run_id: runId } });
    // Advance emulator a few frames so at least one env event with a frame number is emitted
    await page.request.post("http://127.0.0.1:8000/api/action/press", { data: { button: "A", frames: 8 } });

    await page.goto("http://127.0.0.1:5173/", { waitUntil: "domcontentloaded" });
    await expect(page.locator("img.game-screen")).toBeVisible({ timeout: 5000 });

    // Wait for at least one thumbnail to appear in the trace
    await expect(page.locator(".trace-thumbnail")).toBeVisible({ timeout: 5000 });

    // Toggle screenshots off — all thumbnails should disappear
    const screenshotsLabel = page.getByLabel("Trace event filters").locator("label").filter({ hasText: "screenshots" });
    await screenshotsLabel.click();
    await expect(page.locator(".trace-thumbnail")).not.toBeVisible();

    // Toggle back on — thumbnails should reappear
    await screenshotsLabel.click();
    await expect(page.locator(".trace-thumbnail")).toBeVisible();
  } finally {
    await page.request.post("http://127.0.0.1:8000/api/run/stop").catch(() => {});
    rmSync(resolve("..", "runs", runId), { recursive: true, force: true });
    rmSync(resolve("..", "states", runId), { recursive: true, force: true });
  }
});

test("emulator speed controls are labeled and functional without start-run button", async ({ page }) => {
  const errors = [];
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("http://127.0.0.1:5173/", { waitUntil: "domcontentloaded" });

  // Speed controls and label should be present
  await expect(page.getByText("Emulator speed")).toBeVisible();
  await expect(page.getByRole("button", { name: /paused/ })).toBeVisible();
  await expect(page.getByRole("button", { name: "1x" })).toBeVisible();

  // No "Reset run" or "Start run" button in the header
  await expect(page.getByRole("button", { name: "Reset run" })).not.toBeVisible();
  await expect(page.getByRole("button", { name: "Start run" })).not.toBeVisible();

  expect(errors).toEqual([]);
});
