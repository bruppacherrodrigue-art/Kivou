import { mkdirSync } from 'node:fs'
import { resolve } from 'node:path'
import { expect, test } from '@playwright/test'

for (const [name, width, height] of [['desktop', 1440, 900], ['mobile', 390, 844]] as const) {
  test(`retained onboarding ${name}: EUR, bounded review, visible server validation`, async ({ page }) => {
    await page.setViewportSize({ width, height })
    await page.route('**/me', (route) => route.fulfill({ json: {
      user_id: 'usr_legacy_fixture', account_id: 'acc_legacy_fixture', email: 'fixture@example.test',
      account_display_name: 'Fixture locale', locale: 'fr', onboarding_status: 'account_created',
      provisional_profile: false, capabilities: { commercial_cockpit: false },
    } }))
    await page.route('**/target-icps', (route) => route.request().method() === 'GET'
      ? route.fulfill({ json: [] })
      : route.fulfill({ status: 422, json: { detail: [
        { loc: ['body', 'customer_input', 'buyer_trades', 0], msg: 'Choisissez un métier proposé.' },
      ] } }))
    await page.goto('/onboarding')
    await page.getByLabel('Produits et services proposés', { exact: true }).fill('Bardage-' + 'x'.repeat(250))
    await page.getByRole('button', { name: 'Continuer', exact: true }).click()
    await page.getByLabel('Entreprises recherchées', { exact: true }).fill('Routes et génie civil')
    await page.getByLabel('Territoire couvert', { exact: true }).fill('France')
    await page.getByLabel('Mots-clés à surveiller', { exact: true }).fill('Matériaux et composants')
    await page.getByRole('button', { name: 'Continuer', exact: true }).click()
    await expect(page.getByLabel('Devise', { exact: true })).toHaveValue('EUR')
    await expect(page.getByRole('option', { name: 'CHF', exact: true })).toHaveCount(0)
    await page.getByLabel('Nom du profil', { exact: true }).fill('Bardage métallique en France')
    await page.getByLabel('Montant minimum du marché', { exact: true }).fill('50000')
    await page.getByRole('button', { name: 'Continuer', exact: true }).click()
    await expect(page.getByRole('heading', { name: 'Vérifier le profil cible', exact: true })).toBeVisible()
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false)
    const fonts = await page.locator('h1, h2').evaluateAll((elements) => elements.map((element) => getComputedStyle(element).fontFamily))
    expect(fonts.every((font) => !font.includes('Lora'))).toBe(true)
    const directory = resolve('../output/playwright/b2')
    mkdirSync(directory, { recursive: true })
    await page.screenshot({ path: resolve(directory, `legacy-${name}-review.png`), fullPage: true })
    await page.getByRole('button', { name: 'Enregistrer et voir les signaux', exact: true }).click()
    await expect(page.getByLabel('Entreprises recherchées', { exact: true })).toHaveAttribute('aria-invalid', 'true')
    await expect(page.getByRole('alert')).toHaveText('Choisissez un métier proposé.')
    await expect(page.getByRole('alert')).toBeVisible()
    await expect(page).toHaveURL(/\/onboarding$/)
    await page.screenshot({ path: resolve(directory, `legacy-${name}-validation.png`), fullPage: true })
  })
}
