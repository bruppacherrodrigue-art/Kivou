import { readFileSync, readdirSync } from 'node:fs'
import { resolve } from 'node:path'

import { expect, test, type Page } from '@playwright/test'

import {
  LOCAL_REFERENCE_ROUTES,
  VISUAL_DETAILS,
  installReferenceApi,
  normalizeConnectedText,
  type VisualScenario,
} from './fixtures'
import { normalizePublicPricingText } from './normalize-public-pricing.mjs'

const VIEWPORTS = [
  { name: 'desktop', width: 1440, height: 900 },
  { name: 'mobile', width: 390, height: 844 },
] as const

const EXPECTED_GOLDENS = [
  ...LOCAL_REFERENCE_ROUTES.flatMap((route) => (
    [`${route.golden}-desktop.png`, `${route.golden}-mobile.png`]
  )),
  'public-menu-open-mobile.png',
  'dashboard-sidebar-open-mobile.png',
].sort()

test.beforeAll(() => {
  const actual = readdirSync(resolve('tests/visual/reference-goldens')).sort()
  expect(actual).toEqual(EXPECTED_GOLDENS)
})

const HEADINGS: Record<(typeof LOCAL_REFERENCE_ROUTES)[number]['golden'], string> = {
  'public-home': 'Repérez les entreprises qui viennent de gagner un marché public.',
  'public-product': 'Kivou suit ce qui se passe après l’attribution.',
  'public-pricing': 'Choisissez la couverture adaptée à votre prospection.',
  'public-signal': 'H. Hüther GmbH a remporté un marché de 5,22 M€ à Munich.',
  'public-contact': 'Contact',
  'public-legal': 'Informations légales et contractuelles',
  'dashboard-login': 'Retrouver vos signaux',
  'dashboard-signup': 'Commencer avec un ciblage clair',
  'dashboard-overview': 'Vue d’ensemble',
  'dashboard-signals': 'Signaux',
  'dashboard-companies': 'Entreprises',
  'dashboard-targeting': 'Profil de ciblage',
  'dashboard-account': 'Compte',
}

const font = (path: string) => readFileSync(resolve(path)).toString('base64')
const FONT_CSS = [
  '@font-face { font-family: "Instrument Sans Variable"; src: url(data:font/woff2;base64,' + font('node_modules/@fontsource-variable/instrument-sans/files/instrument-sans-latin-wght-normal.woff2') + ') format("woff2"); font-weight: 100 900; font-style: normal; font-display: block; }',
  '@font-face { font-family: "Lora Variable"; src: url(data:font/woff2;base64,' + font('node_modules/@fontsource-variable/lora/files/lora-latin-wght-normal.woff2') + ') format("woff2"); font-weight: 400 700; font-style: normal; font-display: block; }',
  '*, *::before, *::after { animation: none !important; transition: none !important; caret-color: transparent !important; }',
].join('\n')

function observeBrowserFailures(page: Page, scenario: VisualScenario) {
  const failures: string[] = []
  page.on('pageerror', (error) => failures.push('pageerror: ' + error.message))
  page.on('console', (message) => {
    const expectedUnauthenticatedProbe = (
      (scenario === 'public-pricing' || scenario === 'auth')
      && message.text() === 'Failed to load resource: the server responded with a status of 401 (Unauthorized)'
    )
    if (message.type() === 'error' && !expectedUnauthenticatedProbe) {
      failures.push('console: ' + message.text())
    }
  })
  page.on('requestfailed', (request) => {
    failures.push('requestfailed: ' + request.method() + ' ' + request.url())
  })
  return failures
}

async function installDeterministicFonts(page: Page) {
  await page.addStyleTag({ content: FONT_CSS })
  await page.evaluate(async () => {
    await document.fonts.load('400 16px "Instrument Sans Variable"')
    await document.fonts.load('400 16px "Lora Variable"')
    await document.fonts.ready
  })
  const fontsReady = await page.evaluate(() => (
    document.fonts.check('400 16px "Instrument Sans Variable"')
    && document.fonts.check('400 16px "Lora Variable"')
  ))
  expect(fontsReady).toBe(true)
}

async function waitForScenario(
  page: Page,
  scenario: VisualScenario,
  golden: (typeof LOCAL_REFERENCE_ROUTES)[number]['golden'],
) {
  await page.getByRole('heading', { level: 1, name: HEADINGS[golden] }).waitFor()
  await page.waitForLoadState('networkidle')

  if (golden === 'public-pricing') {
    await expect(page.locator('.pricing-grid .price-card')).toHaveCount(4)
  }
  if (golden === 'dashboard-overview') {
    await expect(page.locator('.priority-card[aria-busy="true"]')).toHaveCount(0)
    await expect(page.locator('.recent-list .recent-signal')).toHaveCount(5)
  }
  if (golden === 'dashboard-signals') {
    await expect(page.locator('.signal-list .signal-item')).toHaveCount(6)
    await expect(page.locator('#detail-title')).toHaveText(
      VISUAL_DETAILS.find((detail) => detail.signal_id === 'tm-ausbau-campus-ost')!.contract.title!,
    )
    await expect(page.locator('.signal-note-card textarea')).toBeEnabled()
  }
  if (golden === 'dashboard-companies') {
    await expect(page.locator('.companies-list .company-list-item')).toHaveCount(6)
    await expect(page.locator('.company-detail .company-timeline-item')).toHaveCount(1)
  }
  if (golden === 'dashboard-targeting') {
    await expect(page.locator('.target-definition-card[role="status"]')).toHaveCount(0)
    await expect(page.locator('.target-example-list .target-example.is-included')).toHaveCount(2)
  }
  if (golden === 'dashboard-account') {
    await expect(page.locator('.settings-plan-card .settings-plan-facts')).toHaveCount(1)
  }

  if (scenario === 'public-pricing') {
    await expect(page.locator('[aria-busy="true"]')).toHaveCount(0)
  }
}

async function preparePage(
  page: Page,
  scenario: VisualScenario,
  golden: (typeof LOCAL_REFERENCE_ROUTES)[number]['golden'],
) {
  await installDeterministicFonts(page)
  await waitForScenario(page, scenario, golden)
}

for (const route of LOCAL_REFERENCE_ROUTES) {
  for (const viewport of VIEWPORTS) {
    test(route.golden + ' ' + viewport.name, async ({ page }) => {
      const failures = observeBrowserFailures(page, route.scenario)
      const calls = await installReferenceApi(page, route.scenario)
      await page.setViewportSize(viewport)
      await page.goto(route.local)
      await preparePage(page, route.scenario, route.golden)
      if (route.golden.startsWith('dashboard-')) {
        await normalizeConnectedText(page)
      }
      if (
        route.golden === 'public-home'
        || route.golden === 'public-product'
        || route.golden === 'public-pricing'
        || route.golden === 'public-signal'
      ) {
        await normalizePublicPricingText(page)
      }
      const actual = await page.screenshot({ fullPage: true, animations: 'disabled' })
      expect(actual).toMatchSnapshot(route.golden + '-' + viewport.name + '.png', {
        maxDiffPixelRatio: 0.001,
      })
      expect(calls.some((call) => call.path === '/__unhandled__')).toBe(false)
      expect(failures).toEqual([])
    })
  }
}

test('public menu open mobile', async ({ page }) => {
  const failures = observeBrowserFailures(page, 'public-pricing')
  const calls = await installReferenceApi(page, 'public-pricing')
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/')
  await preparePage(page, 'public-pricing', 'public-home')
  await normalizePublicPricingText(page)
  await page.locator('summary[aria-label="Ouvrir le menu"]').click()
  await expect(page.getByRole('navigation', { name: 'Navigation mobile' })).toBeVisible()
  const actual = await page.screenshot({ fullPage: true, animations: 'disabled' })
  expect(actual).toMatchSnapshot('public-menu-open-mobile.png', {
    maxDiffPixelRatio: 0.001,
  })
  expect(calls.some((call) => call.path === '/__unhandled__')).toBe(false)
  expect(failures).toEqual([])
})

test('dashboard sidebar open mobile', async ({ page }) => {
  const failures = observeBrowserFailures(page, 'connected-pro')
  const calls = await installReferenceApi(page, 'connected-pro')
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/app/dashboard')
  await preparePage(page, 'connected-pro', 'dashboard-overview')
  await page.getByRole('button', { name: 'Ouvrir la navigation' }).click()
  await expect(page.getByRole('dialog', { name: 'Navigation' })).toBeVisible()
  await normalizeConnectedText(page)
  const actual = await page.screenshot({ fullPage: true, animations: 'disabled' })
  expect(actual).toMatchSnapshot('dashboard-sidebar-open-mobile.png', {
    maxDiffPixelRatio: 0.001,
  })
  expect(calls.some((call) => call.path === '/__unhandled__')).toBe(false)
  expect(failures).toEqual([])
})

test('connected text normalization survives a late shell rerender', async ({ page }) => {
  await page.setContent(`
    <div class="dashboard-provider">
      <aside><span>Navigation initiale</span></aside>
      <main><span>Contenu initial</span></main>
    </div>
  `)
  await page.evaluate(() => {
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        const sidebar = document.querySelector('aside')
        if (sidebar) sidebar.innerHTML = '<span>Navigation reconstruite</span>'
      })
    })
  })

  await normalizeConnectedText(page)
  await page.evaluate(() => new Promise<void>((resolve) => {
    requestAnimationFrame(() => requestAnimationFrame(() => resolve()))
  }))

  await expect(page.locator('aside')).toHaveText('Texte')
  await expect(page.locator('main')).toHaveText('Texte')
})
