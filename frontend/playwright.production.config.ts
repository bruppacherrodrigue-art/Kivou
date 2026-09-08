import { defineConfig } from '@playwright/test'
import base from './playwright.config'

const port = Number(process.env.KIVOU_PRODUCTION_TEST_PORT || 4174)
const baseURL = `http://127.0.0.1:${port}`

// Serve Vite's compiled output, never its development CSS pipeline.
export default defineConfig({
  ...base,
  testMatch: ['**/onboarding-production.spec.ts', '**/reference-port.spec.ts'],
  grep: /compiled confirmation|dashboard-onboarding (desktop|mobile)$/,
  projects: [{ name: 'production-build' }],
  use: { ...base.use, baseURL },
  webServer: {
    command: `npm run build && npm run preview -- --host 127.0.0.1 --port ${port} --strictPort`,
    url: baseURL,
    reuseExistingServer: false,
    timeout: 120000,
  },
})
