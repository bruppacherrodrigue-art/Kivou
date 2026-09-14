import { readFileSync, readdirSync } from 'node:fs'
import { resolve } from 'node:path'

import { expect, test, type Page } from '@playwright/test'

import { publishedPresentation } from '../../src/presentation/dashboard/adapters'
import {
  LOCAL_REFERENCE_ROUTES,
  VISUAL_SIGNAL_ITEMS,
  VISUAL_SIGNAL_OFFLINE_ARTIFACTS,
  VISUAL_SIGNAL_UNLOCKED_ITEMS,
  VISUAL_UNLOCKED_ITEMS,
  installReferenceApi,
  normalizeConnectedText,
  type VisualScenario,
} from './fixtures'
import { normalizePublicPricingText } from './normalize-public-pricing.mjs'

const VIEWPORTS = [
  { name: 'desktop', width: 1440, height: 900 },
  { name: 'mobile', width: 390, height: 844 },
] as const

// These pre-V11 three-tab captures remain archived on disk. Their active
// replacement is prospecting-v11.spec.ts; public/auth/target/account baselines
// still use their existing references and unchanged pixel-difference tolerance.
const RETIRED_THREE_TAB_GOLDENS = new Set([
  'dashboard-overview', 'dashboard-overview-discovery', 'dashboard-signals', 'dashboard-companies',
])

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

test('archived today references cover discovery and three-month Essential accounts', () => {
  const todayScenarios = LOCAL_REFERENCE_ROUTES
    .filter((route) => route.local === '/app/dashboard')
    .map((route) => route.scenario)
  expect(todayScenarios).toEqual([
    'connected-essential-veteran',
    'connected-discovery',
  ])
})

test('dashboard-signals adversarial fixture contract', () => {
  expect(VISUAL_SIGNAL_ITEMS).toHaveLength(3)
  expect(VISUAL_SIGNAL_ITEMS.filter((item) => item.locked)).toHaveLength(1)
  expect(VISUAL_SIGNAL_UNLOCKED_ITEMS.map((item) => item.event.clock).sort()).toEqual([
    'award',
    'publication',
  ])

  const publicationItem = VISUAL_SIGNAL_UNLOCKED_ITEMS.find(
    (item) => item.event.clock === 'publication',
  )
  expect(publicationItem?.contract.buyer).toBeNull()
  expect(publicationItem?.factual_display.date.kind).toBe('publication')
  expect(publicationItem?.factual_display.missing_fields).toContain('buyer')
  expect(publicationItem?.analysis.fit.reasons).toEqual([])

  for (const item of VISUAL_SIGNAL_UNLOCKED_ITEMS) {
    expect(item.factual_display.headline).not.toMatch(/pour\s+\d{8,}/)
    expect(item.factual_display.market_summary).not.toBeNull()
    expect(item.winner_enrichment.source.kind).toBe('public_notice')
    expect(Object.hasOwn(item, 'provider_metadata')).toBe(false)
  }

  expect(new Set(VISUAL_UNLOCKED_ITEMS.map((item) => item.winner_enrichment.status))).toEqual(
    new Set(['completed', 'partial', 'in_progress', 'pending', 'failed']),
  )
  expect(VISUAL_UNLOCKED_ITEMS.some((item) => item.contract.amount === null)).toBe(true)
  expect(VISUAL_UNLOCKED_ITEMS.some((item) => item.contract.location === null)).toBe(true)
  expect(VISUAL_SIGNAL_OFFLINE_ARTIFACTS).toHaveLength(2)
})

test('dashboard-companies published fixture contract', () => {
  expect(VISUAL_UNLOCKED_ITEMS).toHaveLength(6)
  expect(new Set(VISUAL_UNLOCKED_ITEMS.map((item) => (
    publishedPresentation(item.presentation)?.artifact_id
  ))).size).toBe(VISUAL_UNLOCKED_ITEMS.length)
  for (const item of VISUAL_UNLOCKED_ITEMS) {
    expect(item.company_key).toMatch(/^cmp_[A-Za-z0-9_-]{12,60}$/)
    const presentation = publishedPresentation(item.presentation)
    expect(presentation).not.toBeNull()
    expect(presentation?.status).toBe('FALLBACK')
    expect(presentation?.content.variant).toBe('FACTUAL_FALLBACK')
    expect(presentation?.content.award_summary).not.toBe(item.contract.title)
    expect(presentation?.content.award_summary).not.toBe(item.event.headline)
  }
})

const HEADINGS: Record<(typeof LOCAL_REFERENCE_ROUTES)[number]['golden'], string> = {
  'public-home': 'Repérez les entreprises qui viennent de gagner un marché public.',
  'public-product': 'Kivou suit ce qui se passe une fois le marché attribué.',
  'public-pricing': 'Choisissez la couverture adaptée à votre prospection.',
  'public-signal': 'Kivou suit ce qui se passe une fois le marché attribué.',
  'public-contact': 'Contact',
  'public-legal': 'Informations légales et contractuelles',
  'dashboard-login': 'Retrouver vos signaux',
  'dashboard-signup': 'Commencer avec un profil cible clair',
  'dashboard-overview': '8 nouveaux marchés depuis mardi',
  'dashboard-overview-discovery': '8 nouveaux marchés depuis mardi',
  'dashboard-signals': 'Signaux',
  'dashboard-companies': 'Entreprises',
  'dashboard-targeting': 'Profil cible',
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

async function resetDocumentScroll(page: Page) {
  await expect.poll(() => page.evaluate(async () => {
    window.scrollTo({ top: 0, left: 0, behavior: 'instant' })
    await new Promise<void>((resolve) => {
      window.requestAnimationFrame(() => resolve())
    })
    return window.scrollY
  })).toBe(0)
}

async function waitForScenario(
  page: Page,
  scenario: VisualScenario,
  golden: (typeof LOCAL_REFERENCE_ROUTES)[number]['golden'],
) {
  await page.getByRole('heading', { level: 1, name: HEADINGS[golden], exact: true }).waitFor()
  await page.waitForLoadState('networkidle')
  if (golden === 'public-pricing') {
    await expect(page.locator('.pricing-grid .price-card')).toHaveCount(3)
    await expect(page.locator('.plan-price')).toHaveText(['Gratuit', /EUR\s*49\s*\/mois/, /EUR\s*99\s*\/mois/])
    await expect(page.locator('.pricing-grid')).not.toContainText('CHF')
  }
  if (golden === 'public-signal') {
    await expect(page).toHaveURL(/\/produit$/)
    await expect(page.getByRole('heading', { level: 1 })).not.toContainText('H. Hüther')
  }
  if (scenario === 'public-pricing') {
    await expect(page.locator('a[href="/exemple-de-signal"]')).toHaveCount(0)
  }
  if (golden === 'dashboard-targeting') {
    await expect(page.locator('.target-definition-card[role="status"]')).toHaveCount(0)
    await expect(page.locator('.target-example-list .target-example.is-included')).toHaveCount(2)
  }
  if (golden === 'dashboard-account') {
    await expect(page.locator('.settings-main [data-ui="screen-header"]')).toHaveCount(1)
    await expect(page.locator('.settings-main [data-ui="screen-segments"]')).toHaveCount(1)
    await expect(page.locator('.settings-plan-card [data-ui="summary-row"]')).toHaveCount(1)
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

for (const route of LOCAL_REFERENCE_ROUTES.filter((route) => !RETIRED_THREE_TAB_GOLDENS.has(route.golden))) {
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
  const navigation = page.getByRole('navigation', { name: 'Navigation mobile' })
  await expect(navigation).toBeVisible()
  await expect(navigation.getByRole('link', { name: 'Exemple de signal' })).toHaveCount(0)
  await expect(navigation.getByRole('link', { name: 'Comment ça marche' })).toHaveAttribute('href', '/produit')
  await expect(navigation.getByRole('link', { name: 'Tarifs' })).toHaveAttribute('href', '/tarifs')
  const actual = await page.screenshot({ fullPage: true, animations: 'disabled' })
  expect(actual).toMatchSnapshot('public-menu-open-mobile.png', {
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

test('connected scroll normalization survives a late history restoration', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.setContent('<main style="height: 2400px">Signals</main>')
  await page.evaluate(() => {
    window.scrollTo(0, 1200)
    window.requestAnimationFrame(() => window.scrollTo(0, 785))
  })

  await resetDocumentScroll(page)
  await page.evaluate(() => new Promise<void>((resolve) => {
    window.requestAnimationFrame(() => resolve())
  }))

  expect(await page.evaluate(() => window.scrollY)).toBe(0)
})
