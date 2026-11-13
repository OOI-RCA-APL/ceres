import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: 'e2e',
  forbidOnly: process.env.CI != null,
  reporter:
    process.env.CI != null
      ? [['list'], ['junit', { outputFile: 'e2e-results/junit.xml' }]]
      : 'list',
  outputDir: 'e2e-results/artifacts',
  use: {
    trace: 'retain-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
})
