import { defineConfig } from "@playwright/test";

const API_URL = (process.env.OMNIGENT_E2E_API_URL ?? "http://127.0.0.1:6767").replace(/\/+$/, "");

export default defineConfig({
  testDir: "./e2e",
  timeout: 240_000,

  fullyParallel: false,
  workers: 1,

  use: {
    baseURL: "http://127.0.0.1:5173",
    headless: true,
    viewport: { width: 1280, height: 720 },
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },

  reporter: [["list"], ["html", { open: "never" }]],

  webServer: {
    command: "npm run dev",
    url: "http://127.0.0.1:5173",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
    // Keep Vite's browser proxy on the same backend used by the Node-side
    // setup and cleanup requests.
    env: { OMNIGENT_URL: API_URL },
  },

  projects: [
    {
      name: "chromium",
      use: { browserName: "chromium" },
    },
  ],
});
