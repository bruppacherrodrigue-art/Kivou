import { readFileSync, readdirSync } from 'node:fs'
import { resolve } from 'node:path'

import { expect, test, type Page } from '@playwright/test'

import { publishedPresentation } from '../../src/reference/dashboard/adapters'
import {
  LOCAL_REFERENCE_ROUTES,
  VISUAL_SIGNAL_DETAILS,
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
  expect(publicationItem?.analysis.fit.reasons).toEqual([])

  for (const item of VISUAL_SIGNAL_UNLOCKED_ITEMS) {
    expect(item.presentation?.status).toBe('FALLBACK')
    expect(item.presentation?.content.variant).toBe('FACTUAL_FALLBACK')
    expect(Object.hasOwn(item, 'provider_metadata')).toBe(false)
    expect(publishedPresentation(item.presentation)).toBe(item.presentation)
  }

  expect(VISUAL_SIGNAL_OFFLINE_ARTIFACTS).toHaveLength(VISUAL_SIGNAL_UNLOCKED_ITEMS.length)
  expect(new Set(
    VISUAL_SIGNAL_OFFLINE_ARTIFACTS.map((artifact) => artifact.presentation.artifact_id),
  ).size).toBe(VISUAL_SIGNAL_OFFLINE_ARTIFACTS.length)
  for (const item of VISUAL_SIGNAL_UNLOCKED_ITEMS) {
    const artifact = VISUAL_SIGNAL_OFFLINE_ARTIFACTS.find(
      (candidate) => candidate.signal_id === item.signal_id,
    )
    expect(artifact).toBeDefined()
    expect(item.presentation).toBe(artifact?.presentation)
    expect(Object.keys(artifact?.provider_metadata ?? {}).sort()).toEqual([
      'model_id',
      'prompt_version',
      'provider',
      'qa_model_id',
      'qa_provider',
    ])
    expect(Object.values(artifact?.provider_metadata ?? {})).toEqual([
      null,
      null,
      null,
      null,
      null,
    ])
    expect(Object.hasOwn(artifact?.presentation ?? {}, 'provider_metadata')).toBe(false)
    expect(publishedPresentation(artifact?.presentation)).toBe(artifact?.presentation)
  }
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
  'public-product': 'Kivou suit ce qui se passe après l’attribution.',
  'public-pricing': 'Choisissez la couverture adaptée à votre prospection.',
  'public-signal': 'H. Hüther GmbH a remporté un marché de 5,22 M€ à Munich.',
  'public-contact': 'Contact',
  'public-legal': 'Informations légales et contractuelles',
  'dashboard-login': 'Retrouver vos signaux',
  'dashboard-signup': 'Commencer avec un ciblage clair',
  'dashboard-overview': 'Vue d’ensemble',
  'dashboard-signals': 'Signaux',
  'dashboard-companies': 'Entreprises attributaires',
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
    const signalItems = page.locator('.signal-list .signal-item')
    const locked = signalItems.filter({ has: page.locator('.signal-lock-note') })
    const awardCard = signalItems.filter({ hasText: 'H. Hüther GmbH' })
    const publicationCard = signalItems.filter({ hasText: 'TM Ausbau GmbH' })
    const awardDetail = VISUAL_SIGNAL_DETAILS.find(
      (detail) => detail.signal_id === 'h-huether-munich',
    )!
    const publicationDetail = VISUAL_SIGNAL_DETAILS.find(
      (detail) => detail.signal_id === 'tm-ausbau-campus-ost',
    )!

    await expect(signalItems).toHaveCount(3)
    await expect(locked).toHaveCount(1)
    await expect(locked).toHaveClass(/\bis-locked\b/)
    await expect(locked.locator('.signal-item-head strong')).toHaveText('Non publié')
    await expect(locked.locator('.signal-item-head > span')).toHaveText('Accès payant requis')
    await expect(locked.locator('.signal-event')).toHaveText(
      'Un marché public vient d’être attribué.',
    )
    await expect(locked.locator('.signal-meta')).toHaveCount(1)
    await expect(locked.locator('.signal-meta')).toHaveText('Non publié · Non publié')
    await expect(locked.locator('.signal-fit')).toHaveText(
      'Date d’attribution : 18 août 2026',
    )
    await expect(locked.locator('.signal-lock-note')).toHaveText(
      'Votre accès actuel conserve cet aperçu sans révéler les données protégées.',
    )
    await expect(
      locked.locator('.signal-match, .published-status, [data-presentation-icon]'),
    ).toHaveCount(0)

    const lockedSource = VISUAL_UNLOCKED_ITEMS.find(
      (item) => item.signal_id === 'gsh-gunzenhausen',
    )!
    const protectedFixtureValues = [
      lockedSource.signal_id,
      lockedSource.company.name,
      lockedSource.contract.buyer?.name,
      lockedSource.contract.title,
      lockedSource.contract.reference,
      lockedSource.event.headline,
      lockedSource.analysis.fit.label,
      ...lockedSource.analysis.fit.reasons,
    ].filter((value): value is string => Boolean(value))
    const lockedMarkup = await locked.evaluate((element) => element.outerHTML)
    for (const protectedValue of protectedFixtureValues) {
      expect(lockedMarkup).not.toContain(protectedValue)
    }
    expect(lockedMarkup).not.toContain('presentation')

    await expect(awardCard.locator('.signal-fit')).toHaveText(
      'Date d’attribution : 14 août 2026',
    )
    await expect(publicationCard.locator('.signal-fit')).toHaveText(
      'Date de publication : 25 août 2026',
    )
    await expect(publicationCard).not.toContainText('Date d’attribution')

    const selected = page.locator('.signal-list .signal-item.is-selected')
    await expect(selected).toHaveCount(1)
    await expect(selected).toHaveAttribute('aria-pressed', 'true')
    await expect(selected).toContainText('Acheteur : Non publié')
    await expect(selected.locator('.signal-match')).toHaveCount(0)
    await expect(page.locator('#detail-title')).toHaveText(
      publicationDetail.presentation!.content.headline,
    )
    await expect(page.locator('.published-status')).toContainText('Faits publiés uniquement')
    const buyerFact = page.locator('.fact-grid div').filter({ has: page.getByText('Acheteur', { exact: true }) })
    await expect(buyerFact).toContainText('Non publié')
    const awardeeFact = page.locator('.fact-grid div').filter({
      has: page.getByText('Entreprise attributaire', { exact: true }),
    })
    await expect(awardeeFact).toContainText('TM Ausbau GmbH')
    const publicationFact = page.locator('.fact-grid > div').filter({
      has: page.getByText('Date de publication', { exact: true }),
    })
    await expect(publicationFact.locator('dt')).toHaveText('Date de publication')
    await expect(publicationFact.locator('dd')).toHaveText('25 août 2026')
    await expect(
      page.locator('.fact-grid dt').filter({ hasText: 'Date d’attribution' }),
    ).toHaveCount(0)
    await expect(page.getByText('Rôle cible non disponible', { exact: true })).toBeVisible()

    await awardCard.focus()
    await expect(awardCard).toBeFocused()
    await page.keyboard.press('Enter')
    await expect(page).toHaveURL(new RegExp(
      `/app/signals/h-huether-munich\\?presentation_artifact_id=${awardDetail.presentation!.artifact_id}$`,
    ))
    await expect(page.locator('#detail-title')).toHaveText(
      awardDetail.presentation!.content.headline,
    )
    await expect(page.locator('#detail-title')).toBeFocused()

    await page.goBack()
    await expect(page).toHaveURL(/\/app\/signals\/tm-ausbau-campus-ost$/)
    await expect(publicationCard).toHaveAttribute('aria-pressed', 'true')
    await expect(page.locator('#detail-title')).toHaveText(
      publicationDetail.presentation!.content.headline,
    )
    await expect(publicationCard).toBeFocused()
    await publicationCard.evaluate((element) => element.blur())
    await expect(publicationCard).not.toBeFocused()
    await resetDocumentScroll(page)

    await expect(page.locator('.signal-note-card textarea')).toBeEnabled()
    expect(await page.evaluate(() => (
      document.documentElement.scrollWidth - document.documentElement.clientWidth
    ))).toBeLessThanOrEqual(1)
    const horizontallyClipped = await page.locator(
      '.workspace-grid, .signal-item, .detail-panel, .facts-card, .signal-note-card',
    ).evaluateAll((elements) => elements
      .filter((element) => element.scrollWidth - element.clientWidth > 1)
      .map((element) => element.className))
    expect(horizontallyClipped).toEqual([])
    const verticallyClipped = await page.locator(
      '.signal-item, .detail-panel, .facts-card, .verification-card, .company-card, .signal-note-card',
    ).evaluateAll((elements) => {
      const documentHeight = Math.max(
        document.documentElement.scrollHeight,
        document.body.scrollHeight,
      )
      return elements.flatMap((element) => {
        const rect = element.getBoundingClientRect()
        const top = rect.top + window.scrollY
        const bottom = rect.bottom + window.scrollY
        const verticalOverflow = element.scrollHeight - element.clientHeight
        if (verticalOverflow <= 1 && top >= -1 && bottom <= documentHeight + 1) return []
        return [{
          className: element.className,
          verticalOverflow,
          top,
          bottom,
          documentHeight,
        }]
      })
    })
    expect(verticallyClipped).toEqual([])
  }
  if (golden === 'dashboard-companies') {
    const cards = page.locator('.companies-list .company-list-item')
    const listPanel = page.locator('.companies-panel')
    const detailPanel = page.locator('.company-detail')
    const selectedItem = VISUAL_UNLOCKED_ITEMS.find(
      (item) => item.signal_id === 'h-huether-munich',
    )!
    const selectedPresentation = publishedPresentation(selectedItem.presentation)!
    await expect(cards).toHaveCount(6)
    await expect(page.locator('.company-detail .company-timeline-item')).toHaveCount(1)
    await expect(cards.filter({ hasText: selectedItem.company.name })).toHaveAttribute(
      'aria-current',
      'true',
    )
    await expect(page.locator('#company-name')).toHaveText(
      selectedPresentation.content.award_summary,
    )
    const workspaceText = await page.locator('.companies-workspace').innerText()
    for (const forbidden of [
      selectedItem.contract.title,
      selectedItem.event.headline,
      selectedItem.event.why_now,
      ...selectedItem.analysis.fit.reasons,
    ].filter((value): value is string => Boolean(value))) {
      expect(workspaceText).not.toContain(forbidden)
    }
    const mobile = (page.viewportSize()?.width ?? 0) < 1180
    if (mobile) {
      await expect(listPanel).toBeHidden()
      await expect(detailPanel).toBeVisible()
      await expect(page.getByRole('button', { name: 'Retour aux attributions' })).toBeVisible()
    } else {
      await expect(listPanel).toBeVisible()
      await expect(detailPanel).toBeVisible()
      const overflow = await page.locator('.companies-workspace').evaluate(() => {
        const list = document.querySelector<HTMLElement>('.companies-panel')
        const detail = document.querySelector<HTMLElement>('.company-detail')
        return {
          list: list ? getComputedStyle(list).overflowY : null,
          detail: detail ? getComputedStyle(detail).overflowY : null,
        }
      })
      expect(overflow).toEqual({ list: 'auto', detail: 'auto' })
    }
    expect(await page.evaluate(() => (
      document.documentElement.scrollWidth - document.documentElement.clientWidth
    ))).toBeLessThanOrEqual(1)
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
