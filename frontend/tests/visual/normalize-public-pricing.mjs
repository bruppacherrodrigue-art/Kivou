const PRICING_RESOURCE_TEXT_SELECTORS = [
  '.home-hero .hero-facts',
  '.offer-matrix > div > span > small',
  '.offer-matrix > p',
  '.pricing-page .pricing-hero .hero-facts',
  '.pricing-page .price-card .plan-billing',
  '.pricing-page .price-card > ul > li',
  '.pricing-page .table-wrap tbody tr:not(:first-child) > th',
  '.pricing-page .table-wrap tbody tr:not(:first-child) > td',
  '.pricing-page .pricing-terms',
  '.pricing-page .final-cta .final-cta-grid > div:first-child > p',
  'main:not(.pricing-page) .final-cta .final-cta-grid > div:first-child > p',
]

/**
 * Normalizes only text that is derived from PricingResource authority.
 * Prices, elements, attributes, classes, and every non-pricing surface remain exact.
 *
 * @param {import('@playwright/test').Page} page
 */
export async function normalizePublicPricingText(page) {
  await page.evaluate(({ selectors }) => {
    const preservedPriceNodes = [
      ...document.querySelectorAll('.offer-matrix > div > b, .pricing-page .plan-price'),
      ...[...document.querySelectorAll('.pricing-page .table-wrap tbody tr')]
        .filter((row) => row.querySelector('th')?.textContent?.trim() === 'Prix mensuel'),
    ]
    const priceTextBefore = preservedPriceNodes.map((node) => node.textContent)
    for (const selector of selectors) {
      for (const element of document.querySelectorAll(selector)) {
        let normalized = false
        for (const node of element.childNodes) {
          if (node.nodeType !== Node.TEXT_NODE || !node.nodeValue?.trim()) continue
          node.nodeValue = normalized ? '' : 'Texte'
          normalized = true
        }
      }
    }
    const priceTextAfter = preservedPriceNodes.map((node) => node.textContent)
    if (JSON.stringify(priceTextAfter) !== JSON.stringify(priceTextBefore)) {
      throw new Error('public pricing normalization changed a displayed price')
    }
  }, { selectors: PRICING_RESOURCE_TEXT_SELECTORS })
}
