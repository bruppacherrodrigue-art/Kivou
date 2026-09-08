import { expect, test } from '@playwright/test'
import { installReferenceApi } from './fixtures'

const longSector = 'Services d’architecture, services de construction, services d’ingénierie et services d’inspection pour les bâtiments publics et les ouvrages de génie civil'

for (const viewport of [
  { name: 'mobile', width: 390, height: 844 },
  { name: 'desktop', width: 1440, height: 900 },
]) {
  test(`compiled confirmation contains long catalogue options on ${viewport.name}`, async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== 'production-build', 'Run with playwright.production.config.ts to test compiled assets.')
    const calls = await installReferenceApi(page, 'connected-onboarding')
    const assets: string[] = []
    const mutations: string[] = []
    page.on('request', (request) => {
      const pathname = new URL(request.url()).pathname
      if (pathname.endsWith('.js') || pathname.endsWith('.css') || pathname === '/@vite/client') assets.push(pathname)
      if (!['GET', 'HEAD'].includes(request.method())) mutations.push(request.method())
    })
    await page.route('**/target-icps/options', (route) => route.fulfill({ json: {
      zones: [
        { code: 'CH-VD', label: 'Vaud', country: 'CH' },
        { code: 'FR-38', label: 'Isère', country: 'FR' },
        { code: 'FR-39', label: 'Jura', country: 'FR' },
        { code: 'FR-40', label: 'Landes', country: 'FR' },
        { code: 'FR-41', label: 'Loir-et-Cher', country: 'FR' },
      ],
      sectors: [
        { prefix: '45', label: 'Travaux de construction' },
        { prefix: '71', label: longSector },
      ],
    } }))
    await page.setViewportSize(viewport)
    await page.goto('/app/confirm-profile')
    await expect(page.getByRole('heading', { name: 'Confirmez votre profil cible', exact: true })).toBeVisible()
    const sector = page.getByLabel('Secteur', { exact: true })
    const zone = page.getByLabel('Zone', { exact: true })
    await expect(sector).toHaveValue('45')
    await expect(zone).toHaveValues(['CH-VD'])
    await page.evaluate(() => document.fonts.ready)

    // Keep the real labels: text normalization hid intrinsic select widths
    // in the earlier golden fixture, particularly long unselected options.
    const metrics = await page.evaluate(() => {
      const measure = (selector: string) => {
        const element = document.querySelector<HTMLElement>(selector)!
        const style = getComputedStyle(element)
        const rectangle = element.getBoundingClientRect()
        return { width: rectangle.width, right: rectangle.right,
          parentWidth: element.parentElement!.getBoundingClientRect().width,
          borderWidth: style.borderTopWidth, background: style.backgroundColor,
          color: style.color, minHeight: style.minHeight }
      }
      return { viewport: innerWidth, documentWidth: document.documentElement.scrollWidth,
        sector: measure('#confirmation-sector'), zone: measure('#confirmation-zone'),
        submit: measure('.onboarding-actions button') }
    })
    await testInfo.attach('compiled-layout-metrics', { body: JSON.stringify({ assets, metrics }, null, 2), contentType: 'application/json' })
    await testInfo.attach('compiled-confirmation', { body: await page.screenshot({ fullPage: true }), contentType: 'image/png' })
    expect(assets.some((asset) => /^\/assets\/.+\.css$/.test(asset))).toBe(true)
    expect(assets.some((asset) => /^\/assets\/.+\.js$/.test(asset))).toBe(true)
    expect(assets).not.toContain('/@vite/client')
    expect.soft(metrics.documentWidth).toBeLessThanOrEqual(viewport.width)
    for (const control of [metrics.sector, metrics.zone]) {
      expect.soft(control.width).toBeLessThanOrEqual(control.parentWidth + 1)
      expect.soft(control.right).toBeLessThanOrEqual(viewport.width)
      expect.soft(parseFloat(control.borderWidth)).toBeGreaterThanOrEqual(1)
    }
    expect.soft(metrics.submit.background).toBe('rgb(83, 103, 163)')
    expect.soft(metrics.submit.color).toBe('rgb(255, 255, 255)')

    await sector.selectOption('71')
    await expect(sector).toHaveValue('71')
    expect.soft(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(viewport.width)
    await sector.selectOption('45')
    await zone.selectOption(['FR-41'])
    await expect(zone).toHaveValues(['FR-41'])
    expect(mutations).toEqual([])
    expect(calls.some((call) => call.path === '/__unhandled__')).toBe(false)
  })
}
