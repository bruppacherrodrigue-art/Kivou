import { expect, test } from '@playwright/test'
import type { Me, TargetIcp, TargetIcpOptions } from '../../src/api/types'
import { installReferenceApi } from './fixtures'

// Synthetic API responses only: these tests never authenticate a real account.
const ME: Me = {
  user_id: 'usr-profile-visual-test',
  email: 'profile-visual@example.test',
  account_id: 'acc-profile-visual-test',
  account_display_name: 'Atelier de démonstration',
  locale: 'fr',
  onboarding_status: 'icp_incomplete',
  provisional_profile: true,
  capabilities: { commercial_cockpit: false },
}

const PROFILE: TargetIcp = {
  target_icp_id: 'icp-profile-visual-test',
  label: 'Bois et charpente',
  status: 'active',
  matching_revision: 1,
  plan_limit: null,
  provisional: true,
  customer_input: {
    offer_summary: 'Charpentes et composants bois pour les entreprises de construction.',
    offers: ['materials_and_components'],
    secondary_offers: [],
    buyer_trades: ['building_construction'],
    secondary_buyer_trades: [],
    territories: ['FR'],
    territory_subdivisions: ['FR-38'],
    sector_cpv_prefixes: ['452611'],
    minimum_contract_value: { currency: 'EUR', minimum_amount: 0, maximum_amount: null },
  },
  missing_fields: [],
  created_at: '2026-09-14T09:00:00Z',
  updated_at: '2026-09-14T09:00:00Z',
}

const OPTIONS: TargetIcpOptions = {
  zones: [
    { code: 'FR-38', label: 'Isère', country: 'FR' },
    { code: 'FR-69', label: 'Rhône', country: 'FR' },
    { code: 'CH-VD', label: 'Vaud', country: 'CH' },
  ],
  sectors: [{ prefix: '45', label: 'Travaux de construction' }],
}

const API_FIXTURES: Record<string, unknown> = {
  'GET /me': ME,
  'GET /target-icps': [PROFILE],
  'GET /target-icps/options': OPTIONS,
}

for (const viewport of [
  { name: 'desktop', width: 1440, height: 900 },
  { name: 'mobile', width: 390, height: 844 },
]) {
  test(`profile confirmation ${viewport.name}: standalone, styled and prefilled`, async ({ page }, testInfo) => {
    const failures: string[] = []
    const apiCalls: string[] = []
    page.on('pageerror', (error) => failures.push(error.message))
    await page.setViewportSize({ width: viewport.width, height: viewport.height })
    await page.route('**/*', async (route) => {
      const request = route.request()
      if (!['fetch', 'xhr'].includes(request.resourceType())) return route.continue()
      const key = `${request.method()} ${new URL(request.url()).pathname}`
      apiCalls.push(key)
      if (!Object.hasOwn(API_FIXTURES, key)) {
        failures.push(`Unexpected API request: ${key}`)
        return route.fulfill({ status: 501, json: { detail: { code: 'unexpected_test_api' } } })
      }
      return route.fulfill({ json: API_FIXTURES[key] })
    })

    try {
      await page.goto('/app/confirm-profile')
      await expect(page.getByRole('heading', {
        level: 1, name: 'Quels marchés vous intéressent ?', exact: true,
      })).toBeVisible()
      await expect(page.getByRole('button', { name: 'Recevoir mes signaux', exact: true })).toBeEnabled()
      await page.evaluate(() => document.fonts.ready)

      await expect(page).toHaveURL(/\/app\/confirm-profile$/)
      await expect(page.getByRole('main')).toHaveCount(1)
      await expect(page.locator('.kivou-sidebar, .dashboard-workspace, .topbar')).toHaveCount(0)
      await expect(page.getByRole('complementary', { name: 'Profil provisoire' })).toHaveCount(0)
      await expect(page.getByText('Personnalisez vos opportunités avec votre profil commercial.', { exact: true })).toHaveCount(0)
      await expect(page.getByRole('button', { name: 'Retirer Isère · FR-38', exact: true })).toBeVisible()
      await expect(page.getByRole('button', { name: 'Retirer Matériaux et composants', exact: true })).toBeVisible()
      await expect(page.getByLabel('Secteur', { exact: true })).toHaveValue('452611')
      await expect(page.getByLabel('Ce que vous vendez', { exact: true })).toHaveValue(PROFILE.customer_input.offer_summary)

      const card = await page.locator('.auth-card').boundingBox()
      const contentWidth = await page.evaluate(() => document.documentElement.clientWidth)
      expect(card).not.toBeNull()
      expect(card!.y).toBeLessThan(180)
      expect(card!.x).toBeGreaterThanOrEqual(12)
      expect(card!.x + card!.width).toBeLessThanOrEqual(contentWidth - 12)
      expect(Math.abs(card!.x - (contentWidth - card!.x - card!.width))).toBeLessThanOrEqual(1)

      const selects = page.locator('.profile-confirmation select')
      await expect(selects).toHaveCount(3)
      for (const select of await selects.all()) {
        await expect(select).toBeVisible()
        const geometry = await select.evaluate((element) => {
          const rect = element.getBoundingClientRect()
          const style = getComputedStyle(element)
          return {
            left: rect.left, right: rect.right, width: rect.width, height: rect.height,
            borderWidth: parseFloat(style.borderTopWidth), borderStyle: style.borderTopStyle,
            multiple: (element as HTMLSelectElement).multiple,
          }
        })
        expect(geometry.multiple).toBe(false)
        expect(geometry.borderStyle).toBe('solid')
        expect(geometry.borderWidth).toBeGreaterThanOrEqual(1)
        expect(geometry.width).toBeGreaterThan(200)
        expect(geometry.height).toBeGreaterThanOrEqual(44)
        expect(geometry.left).toBeGreaterThan(card!.x)
        expect(geometry.right).toBeLessThan(card!.x + card!.width)
      }
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
      expect(new Set(apiCalls)).toEqual(new Set(Object.keys(API_FIXTURES)))
      expect(failures).toEqual([])
    } finally {
      await testInfo.attach(`profile-confirmation-${viewport.name}`, {
        body: await page.screenshot({ fullPage: true, animations: 'disabled' }),
        contentType: 'image/png',
      })
    }
  })

  test(`pricing ${viewport.name}: centered EUR offers with real page text`, async ({ page }, testInfo) => {
    const failures: string[] = []
    page.on('pageerror', (error) => failures.push(error.message))
    const calls = await installReferenceApi(page, 'public-pricing')
    await page.setViewportSize({ width: viewport.width, height: viewport.height })

    try {
      await page.goto('/tarifs')
      await expect(page.getByRole('heading', {
        level: 1, name: 'Choisissez la couverture adaptée à votre prospection.', exact: true,
      })).toBeVisible()
      const cards = page.locator('.pricing-grid .price-card')
      await expect(cards).toHaveCount(3)
      await expect(page.locator('.pricing-grid .plan-price')).toHaveText([
        'Gratuit', /EUR\s*49\s*\/mois/, /EUR\s*99\s*\/mois/,
      ])
      await expect(page.getByRole('main')).toHaveCount(1)
      await expect(page.getByRole('main')).not.toContainText('CHF')
      await expect(page.locator('a[href*="exemple-de-signal"]')).toHaveCount(0)
      await page.evaluate(async () => { await document.fonts.ready })
      const contentWidth = await page.evaluate(() => document.documentElement.clientWidth)

      const geometry = await cards.evaluateAll((elements) => elements.map((element) => {
        const card = element.getBoundingClientRect()
        const price = element.querySelector('.plan-price')!
        const parts = Array.from(price.children).map((part) => part.getBoundingClientRect())
        return {
          left: card.left, right: card.right, top: card.top,
          center: card.left + card.width / 2,
          priceCenter: (Math.min(...parts.map((part) => part.left))
            + Math.max(...parts.map((part) => part.right))) / 2,
        }
      }))
      for (const card of geometry) {
        expect(card.left).toBeGreaterThanOrEqual(12)
        expect(card.right).toBeLessThanOrEqual(contentWidth - 12)
        expect(Math.abs(card.priceCenter - card.center)).toBeLessThanOrEqual(1)
      }
      if (viewport.name === 'desktop') {
        expect(Math.max(...geometry.map((card) => card.top))
          - Math.min(...geometry.map((card) => card.top))).toBeLessThanOrEqual(1)
        const groupCenter = (geometry[0].left + geometry[2].right) / 2
        expect(Math.abs(groupCenter - contentWidth / 2)).toBeLessThanOrEqual(1)
      } else {
        for (const card of geometry) {
          expect(Math.abs(card.center - contentWidth / 2)).toBeLessThanOrEqual(1)
        }
        expect(geometry[1].top).toBeGreaterThan(geometry[0].top)
        expect(geometry[2].top).toBeGreaterThan(geometry[1].top)
      }
      // The comparison table may scroll inside its own wrapper on mobile.
      // The document itself must still fit the viewport.
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
      expect(calls.some((call) => call.path === '/__unhandled__')).toBe(false)
      expect(failures).toEqual([])
    } finally {
      // Keep actual customer-facing wording and amounts in the review artifact.
      await testInfo.attach(`pricing-real-${viewport.name}`, {
        body: await page.screenshot({ fullPage: true, animations: 'disabled' }),
        contentType: 'image/png',
      })
    }
  })
}
