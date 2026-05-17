import { test, expect } from "@playwright/test";
import { rmSync } from "node:fs";
import { resolve } from "node:path";

test("pokemon harness UI starts a run and keeps the screen large", async ({ page }) => {
  const runId = `smoke-${Date.now()}`;
  const errors = [];
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  page.on("pageerror", (error) => errors.push(error.message));

  try {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("http://127.0.0.1:5173/", { waitUntil: "networkidle" });

    await expect(page.getByRole("heading", { name: "Pokemon Harness" })).toBeVisible();
    await expect(page.getByText("WebSocket")).toBeVisible();
    await page.getByLabel("Run id").fill(runId);

    await page.getByRole("button", { name: "Start run", exact: true }).click();
    await expect(page.locator("img.game-screen")).toBeVisible();
    await page.getByRole("button", { name: /^RIGHT$/ }).click();

    const screenBox = await page.locator(".screen-wrap").boundingBox();
    expect(screenBox).not.toBeNull();
    expect(screenBox.width).toBeGreaterThan(650);
    expect(screenBox.height).toBeGreaterThan(550);

    await expect(page.locator(".state-grid")).toContainText("Frame");
    expect(errors).toEqual([]);
  } finally {
    await page.request.post("http://127.0.0.1:8000/api/run/stop").catch(() => {});
    rmSync(resolve("..", "runs", runId), { recursive: true, force: true });
    rmSync(resolve("..", "states", runId), { recursive: true, force: true });
  }
});
