import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 240_000,

  // These tests control real local processes and a real backend session.
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

  // The backend on port 6767 is an explicit prerequisite. The spec performs
  // an API preflight and fails immediately with a useful error when absent.
  webServer: {
    command: "npm run dev",
    url: "http://127.0.0.1:5173",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },

  projects: [
    {
      name: "chromium",
      use: { browserName: "chromium" },
    },
  ],
});
