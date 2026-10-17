import { defineConfig, devices } from "@playwright/test";

const PORT = 3107;
export default defineConfig({
  testDir: "./e2e",
  workers: 1,
  use: { baseURL: `http://localhost:${PORT}` },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: `pnpm build && pnpm exec next start -p ${PORT}`,
    url: `http://localhost:${PORT}`,
    reuseExistingServer: false,
    timeout: 300_000,
  },
});
