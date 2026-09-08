/**
 * Read-only real Discovery QA. Never run automatically in CI.
 * One /a/<opaque-token> URL on stdin only; no CLI arguments, traces or URL logs.
 * Required: QA_ACCOUNT_ID. Optional: QA_ENVIRONMENT=staging|production|local,
 * QA_ORIGIN, QA_VIEWPORT=both|desktop|mobile, QA_OUTPUT_DIR, QA_TIMEOUT_MS,
 * QA_BROWSER_EXECUTABLE, EXPECTED_OPEN_COUNT=1|2|3 (default 3), QA_SCARCITY_REASON,
 * QA_COHORT_AUDIT_FILE: private backend CLI APPLY receipt, dry_run=false.
 * Only after.{account_id,used,quota,remaining,bait_signal_key,grants} is authoritative.
 * API signal_id maps to grants[].signal_key; canonical procedure_references
 * must not overlap. Never use proposed_grants or serialize the audit_token.
 * The audit is required when the API omits procedure IDs; no extra private API calls.
 */
import { createRequire } from 'node:module'
import { mkdir, mkdtemp, readFile, stat, writeFile } from 'node:fs/promises'
import { resolve, join } from 'node:path'
import { performance } from 'node:perf_hooks'
import { persistedAudit, procedureProof } from './discovery-audit.mjs'

process.umask(0o077)
delete process.env.DEBUG
delete process.env.DEBUG_FILE
delete process.env.PWDEBUG
const require = createRequire(import.meta.url)
const started = performance.now()
let stage = 'configuration'
let browser
let output
const report = { status: 'fail', write_attempts: 0, screenshots: [], viewports: [] }
const check = (condition, code) => { if (!condition) throw new Error(code) }
const elapsed = () => Math.round(performance.now() - started)
const string = (value) => typeof value === 'string' && value.trim().length > 0
const named = (value) => string(value) && /\p{L}/u.test(value) && !/^\s*(?:siret|siren)\s*[:#-]?\s*[\d\s.-]+\s*$/i.test(value)

try {
  check(process.argv.length === 2, 'stdin_only')
  const environment = process.env.QA_ENVIRONMENT || 'staging'
  const origins = { staging: 'https://staging.kivou.eu', production: 'https://kivou.eu', local: 'http://127.0.0.1:5173' }
  check(Object.hasOwn(origins, environment), 'environment')
  const origin = new URL(process.env.QA_ORIGIN || origins[environment])
  check(origin.username === '' && origin.password === '' && origin.pathname === '/' && !origin.search && !origin.hash, 'origin')
  check(origin.protocol === 'https:' || (environment === 'local' && origin.protocol === 'http:' && ['localhost', '127.0.0.1'].includes(origin.hostname)), 'origin_protocol')
  const expectedText = process.env.EXPECTED_OPEN_COUNT || '3'
  check(/^[1-3]$/.test(expectedText), 'expected_open_count')
  const expected = Number(expectedText)
  const account = process.env.QA_ACCOUNT_ID
  check(string(account), 'account_required')
  const viewportName = process.env.QA_VIEWPORT || 'both'
  check(['both', 'desktop', 'mobile'].includes(viewportName), 'viewport')
  const timeout = Number(process.env.QA_TIMEOUT_MS || '30000')
  check(Number.isInteger(timeout) && timeout >= 1000 && timeout <= 120000, 'timeout')
  let audit = null
  if (process.env.QA_COHORT_AUDIT_FILE) {
    const auditPath = resolve(process.env.QA_COHORT_AUDIT_FILE)
    const metadata = await stat(auditPath)
    check(metadata.isFile() && (metadata.mode & 0o077) === 0 && metadata.size <= 1024 * 1024, 'private_audit_required')
    audit = persistedAudit(JSON.parse(await readFile(auditPath, 'utf8')), account, expected)
  }
  const scarcity = process.env.QA_SCARCITY_REASON || null
  check(expected === 3 || string(scarcity), 'scarcity_reason_required')
  report.expected_open_count = expected
  report.scarcity_reason = scarcity
  report.environment = environment
  report.account_id = account
  report.audit_supplied = Boolean(audit)
  report.audit_as_of = audit?.as_of ?? null
  const parent = resolve(process.env.QA_OUTPUT_DIR || 'output/playwright/discovery-token')
  await mkdir(parent, { recursive: true, mode: 0o700 })
  output = await mkdtemp(join(parent, `${environment}-`))

  stage = 'stdin'
  let input = ''
  for await (const chunk of process.stdin) {
    input += chunk.toString()
    check(input.length <= 16384, 'input_length')
  }
  const value = input.trim()
  check(!/\s/.test(value), 'one_url_required')
  const tokenUrl = new URL(value)
  check(tokenUrl.origin === origin.origin && !tokenUrl.username && !tokenUrl.password && !tokenUrl.search && !tokenUrl.hash && /^\/a\/[A-Za-z0-9._~-]+$/.test(tokenUrl.pathname), 'token_url')
  input = ''

  stage = 'browser'
  const { chromium, expect } = require('@playwright/test')
  browser = await chromium.launch({ headless: true, ...(process.env.QA_BROWSER_EXECUTABLE ? { executablePath: process.env.QA_BROWSER_EXECUTABLE } : {}) })
  const sizes = [{ name: 'desktop', width: 1440, height: 1000 }, { name: 'mobile', width: 390, height: 844 }]
    .filter((viewport) => viewportName === 'both' || viewport.name === viewportName)
  let firstIds = null
  for (const viewport of sizes) {
    const context = await browser.newContext({ viewport, locale: 'fr-CH', timezoneId: 'UTC', reducedMotion: 'reduce', serviceWorkers: 'block' })
    try {
      const page = await context.newPage()
      page.setDefaultTimeout(timeout)
      const result = { viewport: viewport.name, timings_ms: {}, screenshots: [] }
      report.viewports.push(result)
      await context.route('**/*', async (route) => {
        const request = route.request()
        if (!['GET', 'HEAD'].includes(request.method())) {
          report.write_attempts += 1
          await route.abort('blockedbyclient')
        } else if (new URL(request.url()).origin !== origin.origin) {
          await route.abort('blockedbyclient')
        } else {
          await route.continue()
        }
      })
      let lockedDetailRequests = 0
      let lockedIds = new Set()
      page.on('request', (request) => {
        const pathname = new URL(request.url()).pathname
        if (pathname.startsWith('/signals/') && lockedIds.has(decodeURIComponent(pathname.slice('/signals/'.length)))) lockedDetailRequests += 1
      })
      stage = `${viewport.name}_token`
      await page.goto(tokenUrl.href, { waitUntil: 'domcontentloaded' })
      await page.waitForURL((url) => url.origin === origin.origin && url.pathname.startsWith('/app'))
      const landing = new URL(page.url()).pathname.match(/^\/app\/signals\/([^/]+)$/)
      const bait = audit?.bait_signal_id || (landing ? decodeURIComponent(landing[1]) : null)
      check(string(bait), 'bait_audit_required')
      const meResponse = await context.request.get(`${origin.origin}/me`)
      check(meResponse.status() === 200, 'me_status')
      const me = await meResponse.json()
      check(me.account_id === account && !me.provisional_profile, 'confirmed_account')
      result.timings_ms.token = elapsed()

      const capture = async (name) => {
        const filename = `${viewport.name}-${name}.png`
        const bytes = await page.screenshot({ fullPage: true })
        await writeFile(join(output, filename), bytes, { mode: 0o600, flag: 'wx' })
        result.screenshots.push(filename)
        report.screenshots.push(filename)
      }
      const readVisit = async (reload) => {
        const feedPromise = page.waitForResponse((response) => new URL(response.url()).pathname === '/signals' && response.request().method() === 'GET')
        const dashboardPromise = page.waitForResponse((response) => new URL(response.url()).pathname === '/dashboard' && response.request().method() === 'GET')
        const [feedResponse, dashboardResponse] = await Promise.all([
          feedPromise, dashboardPromise,
          reload ? page.reload({ waitUntil: 'domcontentloaded' }) : page.goto(`${origin.origin}/app/signals`, { waitUntil: 'domcontentloaded' }),
        ])
        check(feedResponse.status() === 200 && dashboardResponse.status() === 200, 'api_status')
        const feed = await feedResponse.json()
        const dashboard = await dashboardResponse.json()
        check(feed.plan_code === 'discovery', 'discovery_plan')
        const grants = feed.items.filter((item) => item.locked === false)
        check(grants.length === expected && dashboard.plan.opened === expected && dashboard.plan.quota === 3, 'observed_open_count')
        check(grants.every((item) => named(item.company?.name) && named(item.contract?.lot_title ?? item.contract?.title ?? item.factual_display?.object_short)), 'named_facts')
        const ids = grants.map((item) => item.signal_id)
        check(new Set(ids).size === expected && ids.includes(bait), 'bait_membership')
        if (audit) check(audit.grants.every((grant) => ids.includes(grant.signal_id)), 'audit_membership')
        const procedures = procedureProof(grants, audit)
        const openRows = page.locator('[data-page="signals"] [data-signal-key]:not([data-locked="true"])')
        await expect(openRows).toHaveCount(expected)
        const rendered = await openRows.evaluateAll((rows) => rows.map((row) => row.getAttribute('data-signal-key')))
        check(JSON.stringify(rendered) === JSON.stringify(ids), 'server_order')
        for (const item of grants) {
          const index = ids.indexOf(item.signal_id)
          await expect(openRows.nth(index)).toContainText(item.company.name)
          const object = item.contract.lot_title ?? item.contract.title ?? item.factual_display.object_short
          const titles = await openRows.nth(index).locator('[title]').evaluateAll((nodes) => nodes.map((node) => node.getAttribute('title')))
          check(titles.includes(object), 'named_object_visible')
        }
        return { ids, grants, procedures, feed, counter: `${dashboard.plan.opened}/${dashboard.plan.quota}` }
      }
      stage = `${viewport.name}_rows`
      const before = await readVisit(false)
      result.actual_open_count = before.ids.length
      result.remaining_slots = audit?.remaining ?? 3 - before.ids.length
      result.counter = before.counter
      result.cohort = before.grants.map((item, index) => ({ signal_id: item.signal_id, ...before.procedures[index], fit_band: item.analysis?.fit?.band ?? null }))
      if (firstIds) check(JSON.stringify(firstIds) === JSON.stringify(before.ids), 'cross_viewport_cohort')
      firstIds = before.ids
      stage = `${viewport.name}_reload`
      const after = await readVisit(true)
      check(JSON.stringify(before.ids) === JSON.stringify(after.ids), 'reload_grants_unchanged')
      result.reload_unchanged = true
      result.timings_ms.rows_and_reload = elapsed()
      if (viewport.name === 'mobile') await page.locator('.sidebar-trigger').click()
      await expect(page.locator('.sidebar-plan-summary')).toContainText(before.counter)
      await capture('counter')
      if (viewport.name === 'mobile') await page.keyboard.press('Escape')
      await capture('signals')
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)
      check(!overflow, 'mobile_overflow')

      stage = `${viewport.name}_locked_preview`
      const locked = after.feed.items.filter((item) => item.locked === true)
      check(locked.length > 0, 'locked_rows_required')
      lockedIds = new Set(locked.map((item) => item.signal_id))
      const offers = page.locator('[data-page="signals"]').getByRole('link', { name: /voir les offres/i })
      await expect(offers).toHaveAttribute('href', '/tarifs')
      const lockedRow = page.locator('[data-page="signals"] [data-locked="true"]').first()
      await lockedRow.getByRole('button').click()
      const preview = page.locator('[data-locked-signal-preview]')
      await expect(preview).toBeVisible()
      await expect(preview).toContainText(locked[0].headline)
      await expect(page.locator('aside[class*="drawer_"]:not([data-locked-signal-preview])')).toHaveCount(0)
      check(lockedDetailRequests === 0, 'locked_detail_request')
      await capture('locked-preview')
      await preview.getByRole('link', { name: 'Voir les offres' }).click()
      await page.waitForURL((url) => url.origin === origin.origin && url.pathname === '/tarifs')
      result.offers_navigation = true
      result.locked_detail_requests = lockedDetailRequests
      result.timings_ms.complete = elapsed()
    } finally {
      await context.close()
    }
  }
  check(report.write_attempts === 0, 'writes_attempted')
  report.status = 'pass'
} catch {
  // Browser exceptions can embed bearer URLs or response bodies. Never serialize them.
  report.failure_stage = stage
  process.exitCode = 1
} finally {
  if (browser) await browser.close().catch(() => { report.status = 'fail'; report.cleanup_failed = true; process.exitCode = 1 })
  report.duration_ms = elapsed()
  if (output) {
    const reportPath = join(output, 'report.json')
    await writeFile(reportPath, JSON.stringify(report, null, 2) + '\n', { mode: 0o600, flag: 'wx' })
    process.stdout.write(JSON.stringify({ status: report.status, report_file: reportPath }) + '\n')
  } else {
    process.stdout.write(JSON.stringify({ status: 'fail', failure_stage: stage }) + '\n')
  }
}
