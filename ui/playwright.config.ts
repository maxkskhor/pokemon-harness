import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: ".",
  webServer: [
    {
      command: "cd .. && uv run uvicorn env.app:app --host 127.0.0.1 --port 8000",
      url: "http://127.0.0.1:8000/api/health",
      reuseExistingServer: true,
      timeout: 30_000,
    },
    {
      command: "npm run dev -- --host 127.0.0.1 --port 5173",
      url: "http://127.0.0.1:5173",
      reuseExistingServer: true,
      timeout: 30_000,
    },
  ],
});
