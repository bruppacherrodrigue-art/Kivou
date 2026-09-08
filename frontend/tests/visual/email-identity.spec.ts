import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { expect, test } from '@playwright/test'
import { installReferenceApi } from './fixtures'

const font = (file: string) => readFileSync(resolve(file)).toString('base64')
const fontCss = [
  '@font-face { font-family: "Instrument Sans Variable"; src: url(data:font/woff2;base64,' + font('node_modules/@fontsource-variable/instrument-sans/files/instrument-sans-latin-wght-normal.woff2') + ') format("woff2"); font-weight: 100 900; font-style: normal; font-display: block; }',
  '@font-face { font-family: "Lora Variable"; src: url(data:font/woff2;base64,' + font('node_modules/@fontsource-variable/lora/files/lora-latin-wght-normal.woff2') + ') format("woff2"); font-weight: 100 900; font-style: normal; font-display: block; }',
  '*, *::before, *::after { animation: none !important; transition: none !important; caret-color: transparent !important; }',
].join('\n')

for (const viewport of [
  { name: 'desktop', width: 1440, height: 900 },
  { name: 'mobile', width: 390, height: 844 },
]) {
  for (const screen of ['settings-profile', 'notifications'] as const) {
    test(`dashboard-${screen} ${viewport.name}`, async ({ page }) => {
      const failures: string[] = []
      page.on('pageerror', (error) => failures.push(error.message))
      const calls = await installReferenceApi(page, 'connected-pro')
      const mutations: string[] = []
      await page.route('**/auth/email', (route) => route.fulfill({ json: {
        email: 'claire@acme.test', verified: true, pending_email: 'nouveau@acme.test',
      } }))
      await page.route('**/notification-preferences', (route) => route.fulfill({ json: {
        email_enabled: true, notification_email: 'claire@acme.test', updated_at: '2026-09-07T09:00:00Z',
      } }))
      // Every state is a local fixture; never send an email during screenshots.
      await page.route('**/auth/email/*', async (route) => {
        mutations.push(route.request().method())
        await route.abort()
      })
      await page.setViewportSize(viewport)
      await page.goto(screen === 'settings-profile' ? '/app/settings/profile' : '/app/notifications')

      if (screen === 'settings-profile') {
        await expect(page.getByRole('form', { name: 'Informations principales', exact: true })).toBeVisible()
        await expect(page.getByText('Adresse vérifiée : claire@acme.test', { exact: true })).toBeVisible()
        await expect(page.getByText('En attente de vérification : nouveau@acme.test', { exact: true })).toBeVisible()
        await expect(page.getByLabel('Adresse professionnelle', { exact: true })).toHaveValue('nouveau@acme.test')
        await expect(page.getByRole('button', { name: 'Renvoyer le lien de vérification', exact: true })).toBeEnabled()
      } else {
        await expect(page.getByRole('form', { name: 'Réception des nouveaux signaux', exact: true })).toBeVisible()
        await expect(page.getByLabel('Adresse de réception', { exact: true })).toHaveAttribute('readonly', '')
        await expect(page.getByRole('link', { name: 'Modifier et vérifier mon adresse email', exact: true })).toHaveAttribute('href', '/app/settings/profile')
        await expect(page.getByRole('switch')).toBeChecked()
        await expect(page.getByLabel('Fréquence', { exact: true })).toBeDisabled()
      }

      await page.waitForLoadState('networkidle')
      await page.addStyleTag({ content: fontCss })
      await page.evaluate(async () => {
        await document.fonts.load('400 16px "Instrument Sans Variable"')
        await document.fonts.load('400 16px "Lora Variable"')
        await document.fonts.ready
        window.scrollTo(0, 0)
      })
      expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1)
      expect(await page.screenshot({ fullPage: true, animations: 'disabled' })).toMatchSnapshot(`dashboard-${screen}-${viewport.name}.png`)
      expect(mutations).toEqual([])
      expect(failures).toEqual([])
      expect(calls.some((call) => call.path === '/__unhandled__')).toBe(false)
    })
  }
}
