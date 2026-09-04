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
  'public-signal': 'H. Hüther GmbH a remporté un marché de 5,22 M€ à Munich.',
  'public-contact': 'Contact',
  'public-legal': 'Informations légales et contractuelles',
  'dashboard-login': 'Retrouver vos signaux',
  'dashboard-signup': 'Commencer avec un profil cible clair',
  'dashboard-overview': '8 nouveaux marchés depuis mardi',
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

/** Le copy interdit de la spec, plus le vocabulaire de l'ancienne page
 *  (addendum Rodrigue). Le tiroir peut être porté hors de `[data-page]` par
 *  le Portal Radix (feuille mobile) : les deux racines sont concaténées. */
async function assertNoForbiddenSignalsCopy(page: Page) {
  const combinedText = await page.evaluate(() => {
    const parts: string[] = []
    const pageRoot = document.querySelector('[data-page="signals"]')
    if (pageRoot) parts.push(pageRoot.textContent ?? '')
    const drawer = document.querySelector('aside')
    if (drawer) parts.push(drawer.textContent ?? '')
    return parts.join(' ')
  })
  const normalized = combinedText.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase()
  for (const forbidden of [
    'documente',
    'non publie',
    'resolution incomplete',
    'faits publies',
    'contact non confirme',
    'signal',
    'profil cible',
    'attribution',
    'deblocage',
    'analyse',
  ]) {
    expect(normalized).not.toContain(forbidden)
  }
}

async function waitForScenario(
  page: Page,
  scenario: VisualScenario,
  golden: (typeof LOCAL_REFERENCE_ROUTES)[number]['golden'],
) {
  // Le golden `dashboard-signals` desktop ouvre un lien profond dont le tiroir
  // sticky peut retarder la mise en accessibilité du reste de l'arbre le
  // temps du premier rendu. Un sélecteur de balise, non tributaire de cet
  // arbre, reste correct dans tous les cas ici (desktop comme mobile, feuille
  // fermée ou tiroir ouvert).
  if (golden === 'dashboard-signals') {
    await page.locator('h1', { hasText: HEADINGS[golden] }).waitFor()
  } else {
    await page.getByRole('heading', { level: 1, name: HEADINGS[golden], exact: true }).waitFor()
  }
  await page.waitForLoadState('networkidle')

  if (golden === 'public-pricing') {
    await expect(page.locator('.pricing-grid .price-card')).toHaveCount(4)
  }
  if (golden === 'dashboard-overview') {
    await expect(page.locator('[data-page="today"] article')).toHaveCount(3)
    await expect(page.getByRole('region', { name: 'À relancer' })).toBeVisible()
    await expect(page.getByRole('region', { name: 'Cette semaine' })).toBeVisible()
  }
  if (golden === 'dashboard-signals') {
    // Nouvelle page : un tableau dense + une ligne de filtres + un tiroir
    // droit sticky. Le golden desktop ouvre ce tiroir sur le signal de
    // publication récente (`tm-ausbau-campus-ost`), sans raisons de
    // correspondance (fixture) — le bloc « Pourquoi ça vous concerne » doit
    // donc être absent, et le bloc « Ce que le titulaire va devoir faire »
    // présent. Le golden mobile, lui, garde la feuille FERMÉE (route sans
    // clé de signal) : c'est le tableau dense qu'il doit montrer, pas le
    // tiroir qui le masquerait entièrement en plein écran.
    const mobile = (page.viewportSize()?.width ?? 0) < 900

    const toolbar = page.locator('[role="toolbar"]')
    await expect(toolbar).toBeVisible()
    await expect(toolbar.locator('[data-segment="new"]')).toContainText('Nouveaux')
    await expect(toolbar.locator('[data-segment="saved"]')).toContainText('Sauvés')
    await expect(toolbar.locator('[data-segment="contacted"]')).toContainText('Contactés')
    await expect(toolbar.locator('[data-segment="ignored"]')).toHaveText('Ignorés')
    await expect(toolbar.locator('[data-segment="all"]')).toHaveText('Tous')

    if (!mobile) {
      // À 1440 px, les filtres tiennent sur UNE ligne : la hauteur de la
      // barre d'outils ne doit pas dépasser 1,5 fois celle du groupe de
      // segments (sans quoi la recherche serait retombée sur une deuxième
      // ligne).
      const toolbarBox = await toolbar.boundingBox()
      const segmentsBox = await toolbar.locator('[role="group"]').boundingBox()
      expect(toolbarBox).not.toBeNull()
      expect(segmentsBox).not.toBeNull()
      expect(toolbarBox!.height).toBeLessThanOrEqual(segmentsBox!.height * 1.5)
    }

    const table = page.locator('table')
    const headers = await table.locator('thead th').allTextContents()
    expect(headers).toEqual(
      mobile
        ? ['Date', 'Titulaire', 'Objet', 'Montant', 'Match']
        : ['Date', 'Titulaire', 'Objet', 'Montant', 'Lieu', 'Match'],
    )
    const rows = table.locator('tbody tr')
    await expect(rows).toHaveCount(3)
    await expect(table).toContainText('H. Hüther GmbH')
    await expect(table).toContainText('TM Ausbau GmbH')

    // Le troisième signal de ce golden est verrouillé (offre Discovery) :
    // sa ligne existe mais ne révèle que le teaser générique du serveur.
    const lockedRow = rows.filter({ hasText: 'Un marché public vient d’être attribué.' })
    await expect(lockedRow).toHaveCount(1)
    await expect(lockedRow).toContainText(
      'Votre accès actuel conserve cet aperçu sans révéler les données protégées.',
    )

    // Le secteur est hors de cette offre : le filtre est désactivé et expliqué.
    await expect(page.locator('#signals-sector-restricted')).toHaveText(
      'Ce filtre n’est pas inclus dans votre accès actuel.',
    )

    if (!mobile) {
      const drawer = page.locator('aside[aria-labelledby]')
      await expect(drawer).toBeVisible()
      await expect(drawer.getByRole('heading', { level: 2 })).toHaveText(
        'Portes intérieures bois du Campus Ost',
      )
      await expect(drawer).toContainText('Acheteur')
      await expect(drawer).toContainText('Ce que le titulaire va devoir faire')
      await expect(drawer.getByText('Pourquoi ça vous concerne', { exact: true })).toHaveCount(0)
      await expect(drawer.getByRole('link', { name: /Source : TED 584863-2026/ })).toBeVisible()
    } else {
      // La feuille reste fermée : aucun tiroir dans le DOM, le tableau seul
      // occupe l'écran.
      await expect(page.locator('[role="dialog"]')).toHaveCount(0)
    }

    await assertNoForbiddenSignalsCopy(page)

    // Aucune des deux largeurs ne doit pousser la page hors du viewport :
    // le tableau et la barre de segments défilent dans leur propre boîte.
    expect(await page.evaluate(() => (
      document.documentElement.scrollWidth - document.documentElement.clientWidth
    ))).toBeLessThanOrEqual(1)
  }
  if (golden === 'dashboard-companies') {
    const rows = page.locator('main table').first().locator('tbody > tr')
    const detailPanel = page.getByRole('complementary')
    const selectedItem = VISUAL_UNLOCKED_ITEMS.find(
      (item) => item.signal_id === 'h-huether-munich',
    )!
    await expect(rows).toHaveCount(6)
    await expect(rows.filter({ hasText: selectedItem.company.name })).toHaveAttribute(
      'aria-current',
      'true',
    )
    await expect(detailPanel).toBeVisible()
    await expect(detailPanel.getByRole('heading', { level: 2 })).toHaveText(selectedItem.company.name!)
    await expect(detailPanel.getByRole('heading', { name: 'Ses marchés' })).toBeVisible()
    await expect(detailPanel.getByRole('textbox', { name: 'Notes' })).toBeVisible()
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
      // Le golden `dashboard-signals` mobile garde la feuille FERMÉE (route
      // sans clé de signal) : ouverte, elle masquerait le tableau dense en
      // plein écran, qui est précisément ce que ce gabarit doit montrer. Le
      // golden desktop, lui, conserve le lien profond et son tiroir ouvert.
      const local = route.golden === 'dashboard-signals' && viewport.name === 'mobile'
        ? '/app/signals'
        : route.local
      await page.goto(local)
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

test('dashboard-signals drawer navigation', async ({ page }) => {
  const failures = observeBrowserFailures(page, 'connected-pro')
  const calls = await installReferenceApi(page, 'connected-pro')

  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/app/signals')
  await installDeterministicFonts(page)
  await page.getByRole('heading', { level: 1, name: 'Signaux' }).waitFor()
  await page.waitForLoadState('networkidle')

  const rows = page.locator('table tbody tr')
  await expect(rows).toHaveCount(3)

  // Un clic sur une ligne ouvre le tiroir droit sur ce signal : l'URL porte
  // sa clé, et le `h2` du tiroir affiche son titre.
  await rows.first().locator('td').first().click()
  await expect(page).toHaveURL(/\/app\/signals\/h-huether-munich$/)
  const drawer = page.locator('aside[aria-labelledby]')
  await expect(drawer.getByRole('heading', { level: 2 })).toHaveText(
    'Menuiseries intérieures et mobilier à Munich',
  )

  // Échap referme le tiroir de bureau et revient à la liste seule.
  await page.keyboard.press('Escape')
  await expect(page).toHaveURL(/\/app\/signals$/)
  await expect(page.locator('aside').getByText('Sélectionnez un signal')).toBeVisible()

  // Un lien profond ouvre directement le tiroir sur le signal demandé.
  await page.goto('/app/signals/tm-ausbau-campus-ost')
  await page.getByRole('heading', { level: 1, name: 'Signaux' }).waitFor()
  await page.waitForLoadState('networkidle')
  await expect(drawer.getByRole('heading', { level: 2 })).toHaveText(
    'Portes intérieures bois du Campus Ost',
  )

  expect(calls.some((call) => call.path === '/__unhandled__')).toBe(false)
  expect(failures).toEqual([])
})

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

test('dashboard Aujourd’hui tient sans défilement à 1280 × 800', async ({ page }) => {
  const failures = observeBrowserFailures(page, 'connected-pro')
  await installReferenceApi(page, 'connected-pro')
  await page.setViewportSize({ width: 1280, height: 800 })
  await page.goto('/app/dashboard')
  await preparePage(page, 'connected-pro', 'dashboard-overview')
  expect(await page.evaluate(() => document.documentElement.scrollHeight)).toBeLessThanOrEqual(800)
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
