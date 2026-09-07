import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

// Runtime QA URL on stdin only: never store the bearer token in the report.
const require = createRequire(new URL('../../package.json', import.meta.url));
const { chromium, expect } = require('@playwright/test');
const [environment, viewportName, sha] = process.argv.slice(2);
assert.ok(['staging', 'production'].includes(environment));
assert.ok(['desktop', 'mobile'].includes(viewportName));
assert.match(sha, /^[a-f0-9]{40}$/);
const url = fs.readFileSync(0, 'utf8').trim();
assert.ok(url.startsWith((environment === 'staging' ? 'https://staging.kivou.eu' : 'https://kivou.eu') + '/a/kqa1.'));
const directory = path.resolve('output/playwright/b2', environment);
fs.mkdirSync(directory, { recursive: true, mode: 0o700 });
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ locale: 'fr-FR', viewport: viewportName === 'mobile'
  ? { width: 390, height: 844 } : { width: 1440, height: 1000 } });
const page = await context.newPage();
page.setDefaultTimeout(20000);
const report = { environment, sha, viewport: viewportName, qa: true, measured_at: new Date().toISOString(), requests: [] };
page.on('requestfinished', (request) => {
  const pathname = new URL(request.url()).pathname;
  report.requests.push({ path: pathname.startsWith('/a/') ? '/a/[redacted]' : pathname,
    method: request.method(), duration_ms: Math.round(request.timing().responseEnd) });
});
try {
  const started = performance.now();
  const meResponse = page.waitForResponse((r) => new URL(r.url()).pathname === '/me' && r.ok());
  await page.goto(url, { waitUntil: 'commit' });
  const heading = page.getByRole('heading', { level: 2, name: 'Couverture - Bardage métallique - Zinguerie', exact: true });
  await expect(heading).toBeVisible();
  report.click_to_drawer_ms = Math.round(performance.now() - started);
  const me = await (await meResponse).json();
  assert.equal(me.provisional_profile, true);
  report.account_id = me.account_id;
  await page.getByRole('button', { name: 'Fermer', exact: true }).click();
  const banner = page.getByRole('link', { name: 'Confirmer mon profil', exact: true });
  await expect(banner).toHaveAttribute('href', '/app/confirm-profile');
  if (viewportName === 'mobile') await page.getByRole('button', { name: 'Ouvrir la navigation', exact: true }).click();
  await expect(page.locator('.sidebar-account-link:visible')).toHaveAttribute('href', '/app/confirm-profile');
  await expect(page.getByRole('link', { name: 'Découverte · profil provisoire', exact: true })).toHaveAttribute('href', '/app/confirm-profile');
  if (viewportName === 'mobile') await page.locator('.sidebar-account-link:visible').click();
  else await banner.click();
  await expect(page).toHaveURL(/\/app\/confirm-profile$/);
  // The URL changes before React removes the feed's own Zone filter.
  await expect(page.getByRole('heading', { level: 1, name: 'Confirmez votre profil cible', exact: true })).toBeVisible();
  await expect(page.getByLabel('Zone', { exact: true })).toHaveValues(['FR-41']);
  await expect(page.getByLabel('Secteur', { exact: true })).toHaveValue('45');
  await expect(page.getByLabel('Secteur', { exact: true }).locator('option:checked')).toHaveText('bardage métallique');
  await expect(page.getByLabel('Ce que vous vendez', { exact: true })).toHaveValue('bardage métallique');
  await expect(page.locator('input, select, textarea')).toHaveCount(3);
  await expect(page.getByRole('progressbar')).toHaveCount(0);
  const font = await page.locator('h1').evaluate((element) => getComputedStyle(element).fontFamily);
  assert.ok(!font.includes('Lora'), 'Confirmation uses the sans-serif screen heading');
  report.heading_font = font;
  await page.screenshot({ path: path.join(directory, viewportName + '-confirmation.png'), fullPage: true });
  await page.getByLabel('Ce que vous vendez', { exact: true }).fill('');
  await page.getByRole('button', { name: 'Recevoir mes signaux', exact: true }).click();
  await expect(page.getByLabel('Ce que vous vendez', { exact: true })).toHaveAttribute('aria-invalid', 'true');
  await expect(page.locator('#confirmation-error-offer')).toHaveText('Décrivez ce que vous vendez.');
  await expect(page).toHaveURL(/\/app\/confirm-profile$/);
  assert.equal(report.requests.filter((r) => r.method === 'PATCH').length, 0);
  await page.screenshot({ path: path.join(directory, viewportName + '-validation.png'), fullPage: true });
  await page.getByLabel('Ce que vous vendez', { exact: true }).fill('Panneaux de bardage métallique et accessoires sur mesure');
  const savedResponse = page.waitForResponse((r) => /^\/target-icps\/[^/]+$/.test(new URL(r.url()).pathname) && r.request().method() === 'PATCH');
  const dashboardResponse = page.waitForResponse((r) => new URL(r.url()).pathname === '/dashboard' && r.ok());
  await page.getByRole('button', { name: 'Recevoir mes signaux', exact: true }).click();
  assert.equal((await savedResponse).status(), 200);
  await expect(page).toHaveURL(/\/app$/);
  const dashboard = await (await dashboardResponse).json();
  assert.ok(dashboard.top3.length >= 1, 'Confirmed profile has at least one card');
  await expect(page.locator('[data-page="today"] article').first()).toBeVisible();
  report.click_to_confirmed_app_ms = Math.round(performance.now() - started);
  report.cards = dashboard.top3.length;
  assert.ok(report.click_to_confirmed_app_ms < 60000, 'B2 must finish below 60 seconds');
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth), false, 'No horizontal overflow');
  await expect(page.getByText('Découverte · profil provisoire', { exact: true })).toHaveCount(0);
  await page.screenshot({ path: path.join(directory, viewportName + '-app.png'), fullPage: true });
  report.status = 'pass';
} catch (error) {
  report.status = 'fail';
  report.error = String(error).replaceAll(url, '[qa-token]');
  await page.screenshot({ path: path.join(directory, viewportName + '-failure.png'), fullPage: true }).catch(() => {});
  process.exitCode = 1;
} finally {
  fs.writeFileSync(path.join(directory, viewportName + '-report.json'), JSON.stringify(report, null, 2), { mode: 0o600 });
  console.log(JSON.stringify(report, null, 2));
  await browser.close();
}
