import { expect, test } from '@playwright/test'
import type { DashboardResponse, FeedPage, LockedFeedItem, UnlockedFeedItem } from '../../src/api/types'
import { installReferenceApi, VISUAL_SIGNAL_ITEMS, VISUAL_SIGNAL_UNLOCKED_ITEMS } from './fixtures'

// These are server-selected grants, deliberately not in identifier order.
// No frontend eligibility, procedure selection, or fit-ranking algorithm.
const grants: UnlockedFeedItem[] = ['qa-z-bait', 'qa-a-second', 'qa-m-third'].map((id, index) => {
  const base = VISUAL_SIGNAL_UNLOCKED_ITEMS[0]
  return {
    ...base, signal_id: id,
    company: { ...base.company, name: ['Atelier du Lac', 'Menuiserie des Alpes', 'Construction du Jura'][index] },
    contract: { ...base.contract, lot_title: `Amenagement du batiment ${index + 1}` },
    source: { ...base.source, procedure_id: `qa-procedure-${index + 1}` },
    analysis: { ...base.analysis, fit: { ...base.analysis.fit, band: index < 2 ? 'strong' : 'promising' } },
  }
})
const lockedBase = VISUAL_SIGNAL_ITEMS.find((item): item is LockedFeedItem => item.locked)!
const locked = Array.from({ length: 7 }, (_, index) => ({
  ...lockedBase, signal_id: `qa-locked-${index}`, headline: `Marche reserve ${index + 1}`,
}))

for (const viewport of [{ name: 'desktop', width: 1440, height: 1000 }, { name: 'mobile', width: 390, height: 844 }]) {
  test(`Discovery token: three distinct named grants, stable reload and locked preview ${viewport.name}`, async ({ page }, testInfo) => {
    await page.setViewportSize(viewport)
    const calls = await installReferenceApi(page, 'connected-discovery')
    const requests: Array<{ method: string; path: string }> = []
    page.on('request', (request) => requests.push({ method: request.method(), path: new URL(request.url()).pathname }))
    const feed: FeedPage = {
      items: [...grants, ...locked], total_returned: 10,
      page: { limit: 20, offset: 0, has_more: false, scan_truncated: false, next_cursor: null },
      excluded: { without_display_name: 0, by_freshness: 0, by_filters: 0, by_status: 0 },
      counts: { new: 3, saved: 0, contacted: 0, ignored: 0 }, counts_available: true, counts_truncated: false,
      read_at: '2026-09-08T12:00:00Z', freshness: 'all', language: 'fr', plan_code: 'discovery', view: 'history',
      history_access: { scope: 'grants_only', history_days: 0 },
      filter_access: { date_range: false, country: true, subdivision: true, status: true, sector: false },
      policy: { feed: 'customer-feed-v0.1', recency: 'v1', paywall: 'kivou-paywall-v0.1' },
    }
    const dashboard: DashboardResponse = {
      as_of: feed.read_at, last_seen_at: null, new_since_last_visit: 3, strong_matches: 2,
      top3: grants, to_follow_up: [], to_follow_up_truncated: false,
      week: { new: 3, saved: 0, contacted: 0, replied: 0 }, scan_truncated: false,
      profile: { name: 'Menuiserie', sector_label: 'Construction', zone_labels: ['Vaud'] },
      plan: { name: 'Découverte', opened: 3, quota: 3, period_end: null },
    }
    await page.route((url) => url.pathname === '/signals', (route) => route.fulfill({ json: feed }))
    await page.route((url) => url.pathname === '/dashboard', (route) => route.fulfill({ json: dashboard }))
    await page.goto('/app/signals')
    const openRows = page.locator('[data-page="signals"] [data-signal-key]:not([data-locked="true"])')
    const assertGrants = async () => {
      await expect(openRows).toHaveCount(3)
      expect(await openRows.evaluateAll((rows) => rows.map((row) => row.getAttribute('data-signal-key'))))
        .toEqual(grants.map((item) => item.signal_id))
      for (const item of grants) {
        await expect(page.locator(`[data-page="signals"] [data-signal-key="${item.signal_id}"]`)).toContainText(item.company.name!)
        await expect(page.locator(`[data-page="signals"] [data-signal-key="${item.signal_id}"] [title="${item.contract.lot_title}"]`)).toBeVisible()
      }
    }
    expect(new Set(grants.map((item) => item.source.procedure_id)).size).toBe(3)
    await assertGrants()
    const requestsBeforeReload = requests.filter((request) => request.path === '/signals').length
    await page.reload()
    await assertGrants()
    // React development effect replay can fetch twice per mount. Reload must
    // fetch again, while assertGrants proves the same three IDs and API order.
    expect(requests.filter((request) => request.path === '/signals').length).toBeGreaterThan(requestsBeforeReload)
    const feedRequest = requests.find((request) => request.path === '/signals')
    expect(feedRequest?.method).toBe('GET')
    if (viewport.name === 'mobile') await page.locator('.sidebar-trigger').click()
    await expect(page.locator('.sidebar-plan-summary')).toContainText('3/3')
    if (viewport.name === 'mobile') await page.keyboard.press('Escape')
    await testInfo.attach(`discovery-${viewport.name}`, { body: await page.screenshot({ fullPage: true }), contentType: 'image/png' })
    const offers = page.locator('[data-page="signals"]').getByRole('link', { name: /voir les offres/i })
    await expect(offers).toHaveAttribute('href', '/tarifs')
    const lockedButton = viewport.name === 'mobile'
      ? page.locator('[data-signal-key="qa-locked-0"] button')
      : page.getByRole('button', { name: locked[0].headline, exact: true })
    await lockedButton.click()
    const preview = page.locator('[data-locked-signal-preview]')
    await expect(preview).toBeVisible()
    await expect(preview).toContainText(locked[0].headline)
    await expect(page).toHaveURL(/\/app\/signals\/qa-locked-0$/)
    // SignalDrawer uses this same drawer class, but must not coexist with the mini-panel.
    await expect(page.locator('aside[class*="drawer_"]:not([data-locked-signal-preview])')).toHaveCount(0)
    expect(requests.filter((request) => request.path === '/signals/qa-locked-0')).toHaveLength(0)
    await testInfo.attach(`discovery-locked-${viewport.name}`, { body: await page.screenshot({ fullPage: true }), contentType: 'image/png' })
    await preview.getByRole('link', { name: 'Voir les offres' }).click()
    await expect(page).toHaveURL(/\/tarifs$/)
    expect(await page.evaluate(() => window.history.state?.usr)).toEqual({ lockedSignalKey: 'qa-locked-0' })
    const pro = page.getByRole('link', { name: 'Choisir Pro', exact: true })
    await expect(pro).toHaveAttribute('href', '/app/billing?plan=pro')
    await pro.click()
    await expect(page).toHaveURL(/\/app\/billing\?plan=pro$/)
    expect(await page.evaluate(() => window.history.state?.usr)).toEqual({ lockedSignalKey: 'qa-locked-0' })
    expect(requests.filter((request) => !['GET', 'HEAD'].includes(request.method))).toEqual([])
    expect(calls.filter((call) => call.path === '/__unhandled__')).toEqual([])
  })
}
