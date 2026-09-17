import { mkdirSync } from 'node:fs'
import { expect, test, type Locator, type Page } from '@playwright/test'
import type { DirectorySearchPage } from '../../src/api/types'
import { VISUAL_COMPANIES, VISUAL_DISCOVERY_STATUS, VISUAL_ICP, VISUAL_ME, VISUAL_PRO_STATUS, VISUAL_SIGNAL_DETAILS } from './fixtures'

// Synthetic contract fixtures for browser QA only. Never imported by application code.
async function installV11Api(page: Page, paid: boolean) {
  const companyKey = 'cmp_directory_552115891'
  const key = 'v11-signal-test'
  const profile = { ...VISUAL_ICP, target_icp_id: 'icp-v11', label: 'Matériaux · Alpes-Maritimes', customer_input: { ...VISUAL_ICP.customer_input, territories: ['FR'], territory_subdivisions: ['FR-06'] } }
  const capabilities = { can_view_company_data: paid, can_enrich_company: paid, can_lookup_contact: paid, can_manage_personal_contact: true, can_follow_company: true, can_take_notes: true }
  const directory = { siren: '552115891', name: 'Atelier Béton Exemple', city: 'Nice', naf_label: 'Construction de réseaux et génie civil', source: 'registre', available_fields: ['phone', 'email', 'website', 'workforce'], fields_locked: !paid,
    ...(paid ? { phone: '04 93 12 34 56', published_email: 'contact@example.com', website_url: 'https://example.com', workforce: { minimum: 50, maximum: 99, precision: 'range' as const }, register_observed_at: '2026-09-12' } : {}) }
  let status = 'new'
  let statusRevision = 0
  let note = ''
  let noteRevision = 0
  const signal = () => ({ ...VISUAL_SIGNAL_DETAILS[0], signal_id: key, status, status_revision: statusRevision, company_key: companyKey, target_icp_id: profile.target_icp_id,
    company: { name: directory.name, country: 'FR', identifier: { scheme: 'SIREN', value: directory.siren } },
    factual_display: { ...VISUAL_SIGNAL_DETAILS[0].factual_display, object_short: 'Ouvrages béton et génie civil à Nice', market_summary: 'Ouvrages béton', headline: 'Ouvrages béton et génie civil à Nice' },
    contract: { ...VISUAL_SIGNAL_DETAILS[0].contract, title: 'Ouvrages béton et génie civil à Nice', lot_title: null, amount: { value: '1492999', currency: 'EUR' }, buyer: { name: 'Collectivité Exemple', country: 'FR', identifier: null }, location: { country: 'FR', locality: 'Nice', subdivision_label: 'Alpes-Maritimes', subdivision_code: 'FR-06', postal_code: '06000' }, dates: { award: '2026-09-10', publication: '2026-09-12', contract_notification: null } },
    analysis: { ...VISUAL_SIGNAL_DETAILS[0].analysis, fit: { ...VISUAL_SIGNAL_DETAILS[0].analysis.fit, target_icp_id: profile.target_icp_id, target_icp_label: profile.label, label: 'Correspond à votre profil' } },
    source: { system: 'BOAMP', notice_id: 'test-2026', url: 'https://www.boamp.fr/', country: 'FR', procedure_id: null },
    commercial_context: { reason: 'Sur ce type de lot, le titulaire sous-traite souvent le béton prêt à l’emploi, et vous êtes fournisseur de béton prêt à l’emploi à Nice.', offer_category: 'materials_and_components' },
    notice_facts: { source_system: 'boamp', source_notice_id: 'test-2026', source_url: 'https://www.boamp.fr/', collected_at: '2026-09-12T10:00:00Z', publication_date: '2026-09-12', lot_identifier: 'LOT-0001', title: 'Ouvrages béton et génie civil à Nice', description: null, awarded_amount: { value: '1492999', currency: 'EUR' }, minimum_amount: null, maximum_amount: null, calendar: { duration: { value: '18', unit: 'MONTH', scope: 'works', period_kind: 'unspecified', source_path: '/test/duration' }, initial_duration: null, maximum_duration: null, renewals: null }, buyers: [{ name: 'Collectivité Exemple' }], contacts: [], available_contact_fields: [], contacts_locked: !paid, notice_status: 'published' },
  })
  const company = () => ({ ...VISUAL_COMPANIES[0], company_key: companyKey, official_identity: { ...VISUAL_COMPANIES[0].official_identity, name: directory.name, identifiers: [{ scheme: 'SIREN', value: directory.siren }], website_url: paid ? 'https://example.com' : null }, city: 'Nice', directory, signals: [signal()], related_signals: [], history: [], note: null, note_revision: 0, note_updated_at: null, canonical_company_key: companyKey, private_subject_key: companyKey, identity_resolution: 'resolved', manual_contact: { contact: null, revision: 0, updated_at: null }, membership: { tracked: true, origin: 'user', revision: 1, tracked_at: '2026-09-12' }, capabilities, contact_lookup: { state: paid ? 'available' : 'locked', remaining: paid ? 19 : 0, monthly_quota: paid ? 20 : 0, source: 'apollo', removal_path: '/contact' } })
  const companyRow = { company_key: companyKey, name: directory.name, city: 'Nice', country: 'FR', awards_count: 2, total_amount: [{ value: '1492999', currency: 'EUR' }], last_award_at: '2026-09-10', contact_status: 'contacted', contacted_at: '2026-09-04', top_fit: 'Correspond à votre profil', tracked: true, origin: 'user' }
  const directoryRow: DirectorySearchPage['items'][number] = { company_key: companyKey, canonical_company_key: companyKey, private_subject_key: companyKey, name: directory.name, city: 'Nice', country: 'FR', directory, tracked: true, capabilities }
  const pageInfo = { limit: 20, cursor: null, next_cursor: null, has_more: false, scan_truncated: false }
  const errors: string[] = []
  const requests: Array<{ path: string; query: URLSearchParams }> = []
  page.on('pageerror', (error) => errors.push(error.message))
  await page.route('**/*', async (route) => {
    const req = route.request()
    const url = new URL(req.url())
    const path = url.pathname
    if (!/^\/(me|target-icps|billing|dashboard|signals|companies)(\/|$)/.test(path)) return route.continue()
    requests.push({ path, query: url.searchParams })
    let body: unknown
    if (path === '/me') body = VISUAL_ME
    else if (path === '/target-icps') body = [profile]
    else if (path === '/target-icps/options') body = { zones: [{ code: 'FR-06', label: 'Alpes-Maritimes', country: 'FR' }], sectors: [] }
    else if (path === '/billing/status') body = paid ? VISUAL_PRO_STATUS : { ...VISUAL_DISCOVERY_STATUS, entitlements: { ...VISUAL_DISCOVERY_STATUS.entitlements, filter_level: 'minimum' } }
    else if (path === '/dashboard') body = { as_of: '2026-09-13', last_seen_at: '2026-09-11', new_since_last_visit: 3, strong_matches: 2, top3: [signal()], to_follow_up: [{ company_key: companyKey, name: directory.name, last_signal: signal(), days_since_contact: 9 }], to_follow_up_truncated: false, scan_truncated: false, week: { new: 7, saved: 3, contacted: 2, replied: 0 }, profile: { name: profile.label, sector_label: 'Matériaux', zone_labels: ['Alpes-Maritimes'] }, plan: paid ? { code: 'pro', name: 'Pro', assigned: null, opened_this_month: 3, quota: null, remaining: null, availability: null, period_end: null } : { code: 'discovery', name: 'Découverte', assigned: 3, opened_this_month: null, quota: 3, remaining: 0, availability: 'complete', period_end: null } }
    else if (path === '/signals') body = { items: [signal()], counts_available: true, counts_truncated: false, counts: { new: status === 'new' ? 1 : 0, saved: status === 'saved' ? 1 : 0, contacted: 0, ignored: 0 }, page: { ...pageInfo, offset: 0 }, history_access: { scope: paid ? 'all_available' : 'grants_only', history_days: null } }
    else if (path === `/signals/${key}`) body = signal()
    else if (path === `/signals/${key}/note`) {
      if (req.method() === 'PUT') { note = req.postDataJSON().note; noteRevision += 1 }
      body = { signal_id: key, note, revision: noteRevision, updated_at: '2026-09-13T10:00:00Z' }
    } else if (path === `/signals/${key}/status`) { status = req.postDataJSON().status; body = { signal_id: key, status, revision: ++statusRevision, updated_at: '2026-09-13T10:00:00Z', interaction: null } }
    else if (path === '/companies') body = { items: url.searchParams.getAll('contact_status').includes('replied') ? [] : [companyRow], counts: { to_contact: 0, contacted: 1, replied: 0 }, total: 1, counts_available: true, counts_truncated: false, page: pageInfo, plan_code: paid ? 'pro' : 'discovery', read_at: '2026-09-13' }
    else if (path === '/companies/directory/options') body = { families: [], departments: [{ code: '06', label: 'Alpes-Maritimes' }] }
    else if (path === '/companies/directory') body = { items: [directoryRow], counts: { total: 1, exact: true }, scope: null, page: pageInfo, read_at: '2026-09-13' }
    else if (path === `/companies/${companyKey}`) body = company()
    else { errors.push(`Unexpected API ${req.method()} ${path}`); return route.fulfill({ status: 501, json: { detail: { code: 'unexpected_test_api' } } }) }
    return route.fulfill({ json: body })
  })
  return { errors, requests, signalKey: key, companyKey }
}

async function expectPageLandmarks(page: Page, heading: string) {
  await expect(page.locator('main')).toHaveCount(1)
  await expect(page.locator('h1')).toHaveCount(1)
  await expect(page.getByRole('heading', { level: 1, name: heading, exact: true })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
}

async function expectNativeFocusTrap(page: Page, dialog: Locator) {
  await expect(dialog).toBeVisible()
  expect(await dialog.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true)
  expect(await dialog.evaluate((element) => element instanceof HTMLDialogElement && element.matches(':modal'))).toBe(true)
  await expect.poll(() => dialog.evaluate((element) => element.contains(document.activeElement))).toBe(true)
  const controls = dialog.locator('button:enabled:visible, a[href]:visible, input:enabled:visible, select:enabled:visible, textarea:enabled:visible, [tabindex="0"]:visible')
  expect(await controls.count()).toBeGreaterThan(2)
  const moveFocus = async (key: 'Tab' | 'Shift+Tab') => {
    await page.keyboard.press(key)
    const focus = await dialog.evaluate((element) => ({ inside: element.contains(document.activeElement), documentFocused: document.hasFocus(), tag: document.activeElement?.tagName }))
    // Chromium's native modal traversal may stop in browser chrome at the
    // boundary (also reproducible with a minimal showModal() document).
    // It must never focus any control in the inert background page.
    if (!focus.inside) {
      expect(focus).toEqual({ inside: false, documentFocused: false, tag: 'BODY' })
      await page.keyboard.press(key)
    }
    expect(await dialog.evaluate((element) => element.contains(document.activeElement))).toBe(true)
  }
  await controls.last().focus()
  await moveFocus('Tab')
  // A scrollable native dialog can itself be a focus stop on narrow screens.
  // Traverse that exact container, never an arbitrary background element.
  if (await dialog.evaluate((element) => element === document.activeElement)) await moveFocus('Tab')
  await expect(controls.first()).toBeFocused()
  await moveFocus('Shift+Tab')
  if (await dialog.evaluate((element) => element === document.activeElement)) await moveFocus('Shift+Tab')
  await expect(controls.last()).toBeFocused()
}

async function sidebarNavigate(page: Page, name: string) {
  const link = page.getByRole('link', { name, exact: true })
  if (!(await link.isVisible())) await page.getByRole('button', { name: 'Ouvrir la navigation', exact: true }).click()
  await link.click()
  await expect(page.getByRole('dialog', { name: 'Navigation', exact: true })).toHaveCount(0)
}

for (const viewport of [{ name: 'desktop', width: 1440, height: 1000 }, { name: 'mobile', width: 390, height: 844 }, { name: 'mobile320', width: 320, height: 740 }]) {
  for (const paid of [true, false]) {
    test(`V11 ${viewport.name} ${paid ? 'paid' : 'discovery'} complete three-tab flow`, async ({ page }) => {
      await page.setViewportSize(viewport)
      const fixture = await installV11Api(page, paid)
      const label = `${viewport.name}-${paid ? 'paid' : 'discovery'}`
      mkdirSync('../output/playwright', { recursive: true })
      await page.goto('/app/dashboard')
      await expect(page.getByRole('heading', { name: 'Vos priorités commerciales' })).toBeVisible()
      await expectPageLandmarks(page, 'Aujourd’hui')
      await page.screenshot({ path: `../output/playwright/v11-today-${label}.png`, fullPage: true })
      const adjustment = page.getByRole('button', { name: 'Ajuster', exact: true })
      await adjustment.click()
      const targetDialog = page.getByRole('dialog', { name: 'Ajuster ma consultation', exact: true })
      await expectNativeFocusTrap(page, targetDialog)
      await expect(targetDialog.getByLabel('Profil cible', { exact: true })).toBeVisible()
      if (paid) await expect(targetDialog.getByLabel('Zone à privilégier', { exact: true })).toContainText('Alpes-Maritimes')
      else await expect(targetDialog.getByLabel('Zone à privilégier', { exact: true })).toHaveCount(0)
      await page.keyboard.press('Escape')
      await expect(targetDialog).toHaveCount(0)
      await expect(adjustment).toBeFocused()

      await page.getByRole('link', { name: 'Ma prospection', exact: true }).click()
      await expectPageLandmarks(page, 'Entreprises')
      await expect(page.getByRole('tab', { name: 'Ma prospection', exact: true })).toHaveAttribute('aria-selected', 'true')
      await page.getByRole('tab', { name: 'Annuaire', exact: true }).click()
      await expect(page.getByRole('tab', { name: 'Annuaire', exact: true })).toHaveAttribute('aria-selected', 'true')
      await expect(page.getByRole('table', { name: 'Entreprises', exact: true })).toContainText('Dans ma prospection')
      await expect(page.getByRole('table', { name: 'Entreprises', exact: true })).not.toContainText('Contactée')
      await page.getByRole('button', { name: 'Filtres', exact: true }).click()
      const department = page.getByRole('combobox', { name: 'Département du siège', exact: true })
      await expect(department).toBeEnabled()
      await department.selectOption('06')
      await expect.poll(() => fixture.requests.some((request) => request.path === '/companies/directory' && request.query.get('department') === '06')).toBe(true)
      await expectPageLandmarks(page, 'Entreprises')
      await page.getByRole('button', { name: 'Filtres', exact: true }).click()
      const directoryOpener = page.getByRole('link', { name: 'Ouvrir le dossier de Atelier Béton Exemple', exact: true })
      await directoryOpener.focus()
      await page.keyboard.press('Enter')
      const directoryDossier = page.getByRole('dialog', { name: 'Dossier entreprise', exact: true })
      await expect(directoryDossier.getByRole('heading', { name: 'Atelier Béton Exemple', exact: true })).toBeVisible()
      await expectNativeFocusTrap(page, directoryDossier)
      await page.keyboard.press('Escape')
      await expect(directoryDossier).toHaveCount(0)
      await expect(directoryOpener).toBeFocused()
      await expect(page.getByRole('tab', { name: 'Annuaire', exact: true })).toHaveAttribute('aria-selected', 'true')

      // Generic navigation remembers the directory, whereas the explicit
      // Today "Ma prospection" link always chooses the prospecting list.
      await sidebarNavigate(page, 'Aujourd’hui')
      await expectPageLandmarks(page, 'Aujourd’hui')
      await sidebarNavigate(page, 'Entreprises')
      await expect(page.getByRole('tab', { name: 'Annuaire', exact: true })).toHaveAttribute('aria-selected', 'true')
      await sidebarNavigate(page, 'Aujourd’hui')
      await page.getByRole('link', { name: 'Ma prospection', exact: true }).click()
      await expect(page.getByRole('tab', { name: 'Ma prospection', exact: true })).toHaveAttribute('aria-selected', 'true')

      await page.goto('/app/signals')
      await expectPageLandmarks(page, 'Signaux')
      const signalOpener = page.getByRole('button', { name: 'Ouvrir : Ouvrages béton et génie civil à Nice' })
      await signalOpener.focus()
      await page.keyboard.press('Enter')
      const drawer = page.getByRole('dialog', { name: 'Détail du signal' })
      await expect(drawer.getByRole('heading', { name: 'Pourquoi ça vous concerne' })).toBeVisible()
      await expectNativeFocusTrap(page, drawer)
      await expect(drawer).not.toContainText(/Idée d’approche|Démarrage probable/)
      await expect(drawer.getByText('Collectivité Exemple', { exact: true })).toHaveCount(1)
      const notes = drawer.getByRole('textbox', { name: 'Vos notes sur ce signal' })
      await notes.fill('Rappeler jeudi — test navigateur')
      await expect(drawer.getByRole('status')).toContainText('Enregistré')
      if (paid) await expect(drawer.getByRole('link', { name: '04 93 12 34 56' })).toBeVisible()
      else {
        await expect(drawer.getByRole('button', { name: 'Voir ce contact — 49 €/mois' })).toBeVisible()
        await expect(drawer).not.toContainText('contact@example.com')
      }
      await drawer.locator('h2').scrollIntoViewIfNeeded()
      await expect(drawer.getByRole('button', { name: 'Fermer', exact: true })).toBeInViewport()
      await page.screenshot({ path: `../output/playwright/v11-signal-${label}.png` })
      await page.keyboard.press('Escape')
      await expect(drawer).toHaveCount(0)
      await expect(signalOpener).toBeFocused()
      await page.keyboard.press('Enter')
      await expect(notes).toHaveValue('Rappeler jeudi — test navigateur')
      await drawer.getByRole('link', { name: 'Atelier Béton Exemple', exact: true }).click()
      await expect(page).toHaveURL(new RegExp(`/app/companies/${fixture.companyKey}`))
      const dossier = page.getByRole('dialog', { name: 'Dossier entreprise' })
      await expect(dossier.getByRole('heading', { name: 'Atelier Béton Exemple' })).toBeVisible()
      await expect(dossier).not.toContainText('Idée d’approche')
      await expect(dossier.getByRole('button', { name: 'Fermer', exact: true })).toBeInViewport()
      await page.screenshot({ path: `../output/playwright/v11-company-${label}.png` })
      await page.goBack()
      await expect(page).toHaveURL(new RegExp(`/app/signals/${fixture.signalKey}(?:\\?|$)`))
      await expect(drawer.getByRole('heading', { name: 'Ouvrages béton et génie civil à Nice', exact: true })).toBeVisible()
      await expect(notes).toHaveValue('Rappeler jeudi — test navigateur')
      await page.goForward()
      await expect(dossier.getByRole('heading', { name: 'Atelier Béton Exemple', exact: true })).toBeVisible()
      await dossier.getByRole('button', { name: 'Fermer', exact: true }).click()
      await page.goto('/app/companies/directory')
      await expectPageLandmarks(page, 'Entreprises')
      await expect(page.getByText('Annuaire complet · Explorez les entreprises au-delà de votre profil cible.')).toBeVisible()
      await expect(page.getByRole('table', { name: 'Entreprises', exact: true })).toContainText('Atelier Béton Exemple')
      await page.screenshot({ path: `../output/playwright/v11-directory-${label}.png`, fullPage: true })
      const directoryRequests = fixture.requests.filter((request) => request.path === '/companies/directory')
      expect(directoryRequests.length).toBeGreaterThan(0)
      expect(directoryRequests.every((request) => !request.query.has('target_icp_id') && !request.query.has('contact_status'))).toBe(true)
      expect(fixture.requests.some((request) => request.path === '/companies' && request.query.get('view') === 'prospection')).toBe(true)
      expect(fixture.errors).toEqual([])
    })
  }
}
