import { mkdirSync } from 'node:fs'
import { expect, test, type Page } from '@playwright/test'
import {
  VISUAL_CATALOGUE,
  VISUAL_DISCOVERY_STATUS,
  VISUAL_LOCKED_ITEMS,
  VISUAL_ME,
  VISUAL_PRO_STATUS,
  installReferenceApi,
} from './fixtures'

const OUTPUT = '../docs/reports/2026-09-18-discovery-paywall'
const locked = VISUAL_LOCKED_ITEMS[0]

async function installLockedPaywall(page: Page, plans: string[], checkoutError = false) {
  await installReferenceApi(page, 'connected-discovery')
  await page.route(`**/signals/${locked.signal_id}**`, async (route) => {
    if (route.request().resourceType() === 'document') return route.fallback()
    return route.fulfill({ json: {
      ...locked,
      access: { granted: false, reason: 'plan_entitlement_required', upgrade_to: plans },
      read_at: '2026-09-18T10:00:00Z',
      language: 'fr',
      landing_example_holder: 'H. Hüther GmbH',
    } })
  })
  if (checkoutError) {
    await page.route('**/billing/checkout', async (route) => route.fulfill({
      status: 503,
      json: { detail: { code: 'billing_unavailable' } },
    }))
  }
}

async function openPaywall(page: Page) {
  await page.goto(`/app/signals/${locked.signal_id}`)
  const detail = page.getByRole('dialog', { name: 'Détail du signal' })
  await expect(detail.getByRole('button', { name: 'Accéder à ce signal' })).toBeVisible()
  await detail.getByRole('button', { name: 'Accéder à ce signal' }).click()
  const paywall = page.getByRole('dialog', { name: 'SIGNAL VERROUILLÉ' })
  await expect(paywall.getByRole('heading', { name: 'Continuez votre prospection' })).toBeVisible()
  return paywall
}

test.beforeEach(() => mkdirSync(OUTPUT, { recursive: true }))

test('capture desktop Essential et Pro', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 })
  await installLockedPaywall(page, ['essential', 'pro'])
  const paywall = await openPaywall(page)
  await expect(paywall.getByRole('heading', { name: 'Essential' })).toBeVisible()
  await expect(paywall.getByRole('heading', { name: 'Pro', exact: true })).toBeVisible()
  await expect(paywall.getByText('Recommandé')).toBeVisible()
  await page.screenshot({ path: `${OUTPUT}/paywall-essential-pro-desktop.png`, fullPage: true })
})

test('capture mobile empilée', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await installLockedPaywall(page, ['essential', 'pro'])
  const paywall = await openPaywall(page)
  await expect(paywall).toBeInViewport()
  expect(await paywall.evaluate((node) => node.scrollWidth <= node.clientWidth)).toBe(true)
  await page.screenshot({ path: `${OUTPUT}/paywall-mobile.png` })
})

test('capture plan unique', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 })
  await installLockedPaywall(page, ['essential'])
  const paywall = await openPaywall(page)
  await expect(paywall.getByRole('heading', { name: 'Essential' })).toBeVisible()
  await expect(paywall.getByRole('heading', { name: 'Pro', exact: true })).toHaveCount(0)
  await page.screenshot({ path: `${OUTPUT}/paywall-plan-unique.png`, fullPage: true })
})

test('capture erreur de création du checkout', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 })
  await installLockedPaywall(page, ['essential', 'pro'], true)
  const paywall = await openPaywall(page)
  await paywall.getByRole('button', { name: /Choisir Essential/ }).click()
  await expect(paywall.getByRole('alert')).toContainText('Facturation indisponible')
  await page.screenshot({ path: `${OUTPUT}/paywall-erreur-checkout.png`, fullPage: true })
})

test('capture retour réussi vers le signal initial', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 })
  await installReferenceApi(page, 'connected-pro')
  await page.route('**/billing/status', async (route) => route.fulfill({ json: VISUAL_PRO_STATUS }))
  await page.addInitScript(({ accountId, signalKey }) => {
    const now = Date.now()
    sessionStorage.setItem('kivou.checkout-intent', JSON.stringify({
      version: 2,
      accountId,
      createdAt: now,
      expiresAt: now + 60 * 60 * 1000,
      target: { kind: 'signal', signalKey },
    }))
  }, { accountId: VISUAL_ME.account_id, signalKey: locked.signal_id })
  await page.goto('/checkout/success')
  await expect(page).toHaveURL(new RegExp(`/app/signals/${locked.signal_id}$`))
  await expect(page.getByRole('dialog', { name: 'Détail du signal' })).toBeVisible()
  await page.screenshot({ path: `${OUTPUT}/checkout-retour-signal.png`, fullPage: true })
})

test('le catalogue visuel de référence conserve les vrais prix', async () => {
  expect(VISUAL_CATALOGUE.plans.find((plan) => plan.plan_code === 'essential')?.monthly_price.eur?.amount_minor_units).toBe(4900)
  expect(VISUAL_CATALOGUE.plans.find((plan) => plan.plan_code === 'pro')?.monthly_price.eur?.amount_minor_units).toBe(9900)
  expect(VISUAL_DISCOVERY_STATUS.discovery.limit).toBe(3)
})
