import assert from 'node:assert/strict'
import { mkdir, writeFile } from 'node:fs/promises'
import { chromium } from 'playwright'

// Recette réelle : node tests/staging/tarifs-eur.mjs [essential|pro|scale].
// Le mode Checkout utilise exclusivement le compte QA et ne soumet aucun paiement.
const origin = 'https://staging.kivou.eu'
const qaEmail = 'pr2b-qa-20260903152743@kivou-qa.ch'
const plans = { essential: { name: 'Essentiel', amount: 29 }, pro: { name: 'Pro', amount: 49 }, scale: { name: 'Scale', amount: 199 } }
const plan = process.argv[2]
assert(!plan || Object.hasOwn(plans, plan), 'Palier inconnu')
const output = process.env.KIVOU_QA_OUTPUT ?? 'output/playwright/tarifs-eur'
await mkdir(output, { recursive: true })
const browser = await chromium.launch()
try {
  const context = await browser.newContext({
    locale: 'fr-FR', viewport: { width: 1440, height: 1100 },
    ...(plan ? { storageState: process.env.KIVOU_QA_STORAGE_STATE } : {}),
  })
  const page = await context.newPage()
  await page.goto(`${origin}/tarifs`)
  await page.getByRole('link', { name: 'Choisir Essentiel', exact: true }).waitFor()
  await page.evaluate(() => document.fonts.ready)
  const body = await page.locator('body').innerText()
  assert(!body.includes('CHF'))
  for (const { name, amount } of Object.values(plans)) {
    const card = page.locator('article').filter({ has: page.getByRole('heading', { name, exact: true }) })
    assert((await card.locator('.plan-price').textContent()).includes(`${amount}\u00a0€`))
    assert((await page.getByRole('table').textContent()).includes(`${amount}\u00a0€`))
  }
  const banned = /occasion|ciblage|déblocage|documenté/i
  const meta = await page.locator('meta[name="description"]').getAttribute('content')
  assert(!banned.test(meta))
  assert(!banned.test(await page.title()))
  assert(!banned.test(await page.getByRole('contentinfo').innerText()))
  for (const tag of await page.locator('meta[property^="og:"]').all()) assert(!banned.test(await tag.getAttribute('content')))
  await page.screenshot({ path: `${output}/tarifs-desktop.png`, fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.screenshot({ path: `${output}/tarifs-mobile.png`, fullPage: true })
  const proof = { origin, prices: [29, 49, 199], currency: 'eur', bodyChfCount: 0, meta }
  if (plan) {
    const me = await context.request.get(`${origin}/me`)
    assert.equal(me.status(), 200)
    assert.equal((await me.json()).email, qaEmail)
    await page.goto(`${origin}/app/billing?plan=${plan}`)
    await page.getByLabel('Offre', { exact: true }).selectOption(plan)
    const responsePromise = page.waitForResponse((r) => r.url() === `${origin}/billing/checkout` && r.request().method() === 'POST')
    await page.getByRole('button', { name: `Choisir ${plans[plan].name}`, exact: true }).click()
    const response = await responsePromise
    assert.equal(response.status(), 200, 'Checkout doit ouvrir une session')
    const payload = await response.json()
    const destination = new URL(payload.checkout_url)
    assert.equal(destination.hostname, 'checkout.stripe.com')
    const sessionId = destination.pathname.split('/').at(-1)
    assert(sessionId.startsWith('cs_test_'), 'Seules les sessions Stripe test sont admises')
    await page.waitForURL('https://checkout.stripe.com/**')
    await page.getByText(qaEmail, { exact: false }).first().waitFor({ timeout: 30000 })
    const text = await page.locator('body').innerText()
    assert(!text.includes('CHF'))
    assert(text.includes('€'))
    assert(new RegExp(`(?:^|\\s)${plans[plan].amount}(?:[,.]00)?\\s*€`).test(text), 'Montant EUR attendu sur Stripe Checkout')
    await page.screenshot({ path: `${output}/checkout-${plan}.png`, fullPage: true })
    Object.assign(proof, { plan, amount: plans[plan].amount, sessionId, paymentSubmitted: false })
  }
  await writeFile(`${output}/${plan ?? 'tarifs'}.json`, JSON.stringify(proof, null, 2), { mode: 0o600 })
  console.log(JSON.stringify(proof))
} finally {
  await browser.close()
}
