import { defineConfig, devices } from "@playwright/test";

// The demo walk-through crosses both zones, so it runs on the one origin (http://localhost:3000) with BOTH dev
// servers: the buyer app on 3000 and the seller app on 3001 behind its /sell rewrite. Already running servers are
// reused; otherwise Playwright starts them. Run: pnpm test:e2e:demo
export default defineConfig({
  testDir: "./e2e-demo",
  workers: 1,
  timeout: 120_000,
  // Dev servers compile each route on its first visit, which can take longer than the default 5 s.
  expect: { timeout: 30_000 },
  use: { baseURL: "http://localhost:3000", trace: "retain-on-failure" },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
    { name: "phone", use: { ...devices["Desktop Chrome"], viewport: { width: 390, height: 844 } } },
  ],
  webServer: [
    { command: "pnpm dev", cwd: "../seller", url: "http://localhost:3001/sell", reuseExistingServer: true, timeout: 120_000 },
    { command: "pnpm dev", url: "http://localhost:3000", reuseExistingServer: true, timeout: 120_000 },
  ],
});
