import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

// Real, single-send QA recipe. Creating this file does not run it.
// Required: QA_TARGET_EMAIL; exactly one /a/<token> URL on stdin, never argv.
// Optional: QA_ENVIRONMENT=staging|production|local (default staging),
// QA_ORIGIN, QA_VIEWPORT=desktop|mobile, QA_OUTPUT_DIR, QA_TIMEOUT_MS,
// QA_BROWSER_EXECUTABLE (otherwise use Playwright's installed Chromium).
// QA_PREVIEW_ONLY=1 stops after the prefilled confirmation screenshot, without
// submitting the profile or requesting an email. API reads remain real.
// Example, only when a real send is explicitly authorized:
// QA_TARGET_EMAIL=recipient@example.test node tests/qa/email-identity.mjs < /private/qa-url
// The private report contains the account/email identity. Stdout contains only
// status and its file path. No traces, HAR, storage state, or browser logs.
// Stops before verification; the user must read the mailbox and click the link.

process.umask(0o077);
// Playwright debug logs can include bearer URLs, including on failed navigation.
delete process.env.DEBUG;
delete process.env.DEBUG_FILE;
delete process.env.PWDEBUG;
const require = createRequire(new URL('../../package.json', import.meta.url));
const { chromium, expect } = require('@playwright/test');

const started = performance.now();
const report = {
  recipe: 'email-identity',
  status: 'fail',
  measured_at: new Date().toISOString(),
  account_id: null,
  email_state: { before: null, after: null },
  timings_ms: {},
  requests: [],
  email_request_attempts: 0,
  verification_attempts: 0,
  screenshots: [],
};
let stage = 'configuration';
let browser;
let directory;
let reportFile;

const elapsed = () => Math.round(performance.now() - started);
const privateWrite = (name, contents) => fs.writeFileSync(path.join(directory, name), contents, { mode: 0o600, flag: 'wx' });
const identityFields = (body) => {
  assert.equal(typeof body.email, 'string');
  assert.equal(typeof body.verified, 'boolean');
  assert.ok(body.pending_email === null || typeof body.pending_email === 'string');
  return { email: body.email, verified: body.verified, pending_email: body.pending_email };
};

qaFlow: try {
  assert.equal(process.argv.length, 2, 'Configuration is via environment; the URL is stdin-only.');
  const previewOnly = process.env.QA_PREVIEW_ONLY === '1';
  const environment = process.env.QA_ENVIRONMENT || 'staging';
  assert.ok(['staging', 'production', 'local'].includes(environment));
  const viewport = process.env.QA_VIEWPORT || 'desktop';
  assert.ok(['desktop', 'mobile'].includes(viewport));
  const timeout = Number(process.env.QA_TIMEOUT_MS || 30000);
  assert.ok(Number.isFinite(timeout) && timeout >= 1000 && timeout <= 120000);
  const targetEmail = (process.env.QA_TARGET_EMAIL || '').trim().toLowerCase();
  assert.match(targetEmail, /^[^\s@]+@[^\s@]+\.[^\s@]+$/);
  const defaultOrigin = environment === 'production' ? 'https://kivou.eu'
    : environment === 'staging' ? 'https://staging.kivou.eu' : 'http://localhost:5173';
  const originUrl = new URL(process.env.QA_ORIGIN || defaultOrigin);
  assert.equal(originUrl.pathname, '/');
  assert.ok(!originUrl.username && !originUrl.password && !originUrl.search && !originUrl.hash);
  assert.ok(originUrl.protocol === 'https:' || (environment === 'local' && originUrl.protocol === 'http:'));
  const origin = originUrl.origin;

  // Parse inside the guarded block: malformed URL exceptions also contain input.
  const input = fs.readFileSync(0, 'utf8').trim();
  assert.ok(input.length > 0 && input.length <= 16384 && !/\s/.test(input));
  const qaUrl = new URL(input);
  assert.equal(qaUrl.origin, origin);
  assert.ok(!qaUrl.username && !qaUrl.password && !qaUrl.search && !qaUrl.hash);
  assert.match(qaUrl.pathname, /^\/a\/[A-Za-z0-9._~-]+$/);

  const root = path.resolve(process.env.QA_OUTPUT_DIR || 'output/playwright/email-identity');
  fs.mkdirSync(root, { recursive: true, mode: 0o700 });
  directory = fs.mkdtempSync(path.join(root, `${environment}-${viewport}-`));
  reportFile = path.join(directory, 'report.json');
  report.environment = environment;
  report.viewport = viewport;

  stage = 'launch_browser';
  browser = await chromium.launch({
    headless: true,
    ...(process.env.QA_BROWSER_EXECUTABLE ? { executablePath: process.env.QA_BROWSER_EXECUTABLE } : {}),
  });
  const context = await browser.newContext({
    locale: 'fr-FR',
    serviceWorkers: 'block',
    viewport: viewport === 'mobile' ? { width: 390, height: 844 } : { width: 1440, height: 1000 },
  });
  const page = await context.newPage();
  page.setDefaultTimeout(timeout);
  page.setDefaultNavigationTimeout(timeout);
  let profileMutationAttempts = 0;
  if (previewOnly) {
    await context.route('**/target-icps**', async (route) => {
      if (['GET', 'HEAD'].includes(route.request().method())) return route.continue();
      profileMutationAttempts += 1;
      return route.abort('blockedbyclient');
    });
  }

  // Prevent an accidental second send or any verification, even if the UI
  // regresses. Aborted attempts still fail the final counters.
  await context.route('**/auth/email/request', async (route) => {
    if (route.request().method() !== 'POST') return route.continue();
    report.email_request_attempts += 1;
    if (previewOnly || report.email_request_attempts > 1) return route.abort('blockedbyclient');
    return route.continue();
  });
  await context.route('**/auth/email/verify', async (route) => {
    report.verification_attempts += 1;
    await route.abort('blockedbyclient');
  });
  page.on('requestfinished', (request) => {
    const url = new URL(request.url());
    if (url.origin !== origin) return;
    // Only fixed endpoint labels are recorded, never arbitrary paths,
    // request bodies, redirect locations, query strings, or fragments.
    const label = url.pathname.startsWith('/a/') ? '/a/[redacted]'
      : /^\/target-icps\/[^/]+$/.test(url.pathname) ? '/target-icps/[id]'
      : ['/me', '/auth/email', '/auth/email/request', '/dashboard'].includes(url.pathname) ? url.pathname : null;
    if (label) report.requests.push({ endpoint: label, method: request.method(), duration_ms: Math.round(request.timing().responseEnd) });
  });
  const read = async (endpoint) => {
    const response = await context.request.get(origin + endpoint, { timeout, maxRedirects: 0 });
    assert.equal(response.status(), 200);
    return response.json();
  };
  const screenshot = async (name) => {
    privateWrite(name, await page.screenshot({ fullPage: true, animations: 'disabled' }));
    report.screenshots.push(name);
  };

  stage = 'follow_token_and_check_identity';
  await page.goto(qaUrl.href, { waitUntil: 'domcontentloaded' });
  await page.waitForURL((url) => url.origin === origin && url.pathname.startsWith('/app/'));
  const me = await read('/me');
  assert.equal(me.email, targetEmail, 'The token must resolve to the actual target mailbox.');
  assert.equal(me.provisional_profile, true);
  assert.equal(typeof me.account_id, 'string');
  assert.ok(me.account_id.length > 0);
  report.account_id = me.account_id;
  const before = identityFields(await read('/auth/email'));
  report.email_state.before = before;
  assert.equal(before.email, targetEmail);
  assert.equal(before.verified, false);
  assert.equal(before.pending_email, null, 'Use a fresh QA identity; this recipe never resends.');
  report.timings_ms.token_to_identity = elapsed();

  stage = 'four_prefilled_confirmation_fields';
  await page.goto(origin + '/app/confirm-profile', { waitUntil: 'domcontentloaded' });
  await expect(page.getByRole('heading', { level: 1, name: 'Confirmez votre profil cible', exact: true })).toBeVisible({ timeout });
  const form = page.locator('form').filter({ has: page.locator('#confirmation-email') });
  await expect(form.locator('input, select, textarea')).toHaveCount(4);
  const zone = form.getByLabel('Zone', { exact: true });
  const sector = form.getByLabel('Secteur', { exact: true });
  const offer = form.getByLabel('Ce que vous vendez', { exact: true });
  const email = form.getByLabel('Adresse professionnelle', { exact: true });
  await expect(zone).toBeEnabled();
  assert.ok(await zone.evaluate((element) => element.selectedOptions.length > 0 && Array.from(element.selectedOptions).every((option) => option.value && !option.disabled)));
  assert.ok((await sector.inputValue()).trim());
  assert.ok((await offer.inputValue()).trim());
  await expect(email).toHaveValue(targetEmail);
  await expect(email).toBeEditable();
  await screenshot('confirmation.png');
  report.timings_ms.token_to_confirmation = elapsed();

  if (previewOnly) {
    assert.equal(profileMutationAttempts, 0);
    assert.equal(report.email_request_attempts, 0);
    assert.equal(report.verification_attempts, 0);
    report.status = 'pass';
    report.preview_only = true;
    report.stopped_before_verification = true;
    // Breaking the labeled try still runs finally: close the browser and
    // write the private report, without creating any submission promises.
    break qaFlow;
  }

  stage = 'submit_once_and_wait_for_smtp';
  const submittedAt = performance.now();
  let profileConfirmed = false;
  const profileResponse = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return url.origin === origin && /^\/target-icps\/[^/]+$/.test(url.pathname) && response.request().method() === 'PATCH';
  }).then(async (response) => {
    report.profile_response_status = response.status();
    assert.equal(response.status(), 200);
    const saved = await response.json();
    assert.equal(saved.provisional, false);
    assert.deepEqual(saved.missing_fields, []);
    profileConfirmed = true;
    report.timings_ms.submit_to_profile_confirmed = Math.round(performance.now() - submittedAt);
  });
  const sentResponse = page.waitForResponse((response) => response.url() === origin + '/auth/email/request' && response.request().method() === 'POST')
    .then(async (response) => {
      report.email_request_status = response.status();
      // A 422, 409, 429, or 503 fails here. No retry or resend is performed.
      assert.equal(response.status(), 200);
      assert.deepEqual(await response.json(), { status: 'sent' });
      assert.deepEqual(response.request().postDataJSON(), { email: targetEmail });
      report.timings_ms.submit_to_smtp_accepted = Math.round(performance.now() - submittedAt);
    });
  await Promise.all([
    profileResponse,
    sentResponse,
    form.getByRole('button', { name: 'Recevoir mes signaux', exact: true }).click(),
  ]);
  assert.equal(profileConfirmed, true);

  stage = 'first_signals_and_awaiting_verification';
  await page.waitForURL((url) => url.origin === origin && url.pathname === '/app' && !url.search && !url.hash);
  const dashboard = page.locator('[data-page="today"]');
  await expect(dashboard.getByRole('heading', { level: 1, name: 'Vos premiers signaux', exact: true })).toBeVisible({ timeout });
  await expect(dashboard.locator('article').first()).toBeVisible({ timeout });
  const notice = dashboard.getByRole('status');
  await expect(notice).toContainText(`Un email de confirmation a été envoyé à ${targetEmail}`);
  await expect(notice).toContainText('Votre adresse est en attente de vérification.');
  report.cards = await dashboard.locator('article').count();
  report.timings_ms.submit_to_first_signals = Math.round(performance.now() - submittedAt);
  const after = identityFields(await read('/auth/email'));
  report.email_state.after = after;
  assert.equal(after.email, targetEmail);
  assert.equal(after.verified, false);
  assert.equal(after.pending_email, targetEmail);
  // The identity read must leave the first-visit heading visible.
  await expect(dashboard.getByRole('heading', { level: 1, name: 'Vos premiers signaux', exact: true })).toBeVisible();
  await screenshot('first-signals-awaiting-verification.png');
  assert.equal(report.email_request_attempts, 1);
  assert.equal(report.verification_attempts, 0);
  report.status = 'pass';
  report.stopped_before_verification = true;
} catch {
  // Never serialize Playwright/URL errors: even their call logs can contain
  // the raw attribution token or a redirect fragment. Fixed stages suffice.
  report.failure = { stage, reason: 'Check failed. Inspect private artifacts and response statuses; no resend was attempted.' };
  process.exitCode = 1;
} finally {
  if (browser) {
    try { await browser.close(); } catch {
      report.status = 'fail';
      report.failure = { stage: 'close_browser', reason: 'Browser cleanup failed.' };
      process.exitCode = 1;
    }
  }
  report.timings_ms.total = elapsed();
  if (directory) {
    try { privateWrite('report.json', JSON.stringify(report, null, 2) + '\n'); } catch {
      reportFile = null;
      report.status = 'fail';
      process.exitCode = 1;
    }
  }
  process.stdout.write(JSON.stringify({ status: report.status, report_file: reportFile ?? null }) + '\n');
}
