import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  timeout: 240000,
  use: {
    // Headless by default so the suite runs on CI runners without a display.
    // Pass `--headed` locally to watch the run.
    headless: true,
    viewport: { width: 1280, height: 720 },
  },
  // Auto-start the Vite dev server, reusing one if it is already running.
  // NOTE: the backend API (http://localhost:6767) is NOT started here and
  // must be running separately before invoking this suite.
  webServer: {
    command: 'npm run dev',
    url: 'http://localhost:5173',
    reuseExistingServer: true,
    timeout: 120000,
  },
  projects: [
    {
      name: 'chromium',
      use: { browserName: 'chromium' },
    },
  ],
});
