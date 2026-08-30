import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './tests/visual',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [
    ['list'],
    ['html', { open: 'never', outputFolder: 'playwright-report' }],
  ],
  updateSnapshots: 'none',
  snapshotPathTemplate: '{testDir}/reference-goldens/{arg}{ext}',
  expect: { toMatchSnapshot: { maxDiffPixelRatio: 0.001 } },
  use: {
    baseURL: 'http://127.0.0.1:5173',
    browserName: 'chromium',
    locale: 'fr-CH',
    timezoneId: 'UTC',
    colorScheme: 'light',
    reducedMotion: 'reduce',
    deviceScaleFactor: 1,
  },
  webServer: {
    command: 'npm run dev -- --host 127.0.0.1',
    url: 'http://127.0.0.1:5173',
    reuseExistingServer: false,
  },
})
