import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const source = (name: string) => resolve(process.cwd(), 'src', name)

test('serves confirm-profile and no longer ships the old onboarding surface', () => {
  const app = readFileSync(source('App.tsx'), 'utf8')
  expect(app).toContain('confirm-profile')
  expect(app).not.toContain('path="onboarding"')
  expect(existsSync(source('pages/Onboarding.tsx'))).toBe(false)
  expect(existsSync(source('presentation/dashboard/OnboardingFlow.tsx'))).toBe(false)
})

test('removes the obsolete cockpit client and component files', () => {
  const endpoints = readFileSync(source('api/endpoints.ts'), 'utf8')
  expect(endpoints).not.toContain('/internal/commercial-cockpit')
  expect(existsSync(source('cockpit/CommercialCockpit.tsx'))).toBe(false)
  expect(existsSync(source('cockpit/CommercialCockpit.module.css'))).toBe(false)
})

test('does not expose the retired commercial plan in active frontend source', () => {
  const files = [
    'api/types.ts',
    'billing/planRoute.ts',
    'pages/Billing.tsx',
    'pages/PublicPricing.tsx',
    'presentation/public/PricingResource.tsx',
  ]
  const retired = ['s', 'c', 'a', 'l', 'e'].join('')
  for (const file of files) expect(readFileSync(source(file), 'utf8').toLowerCase()).not.toContain(retired)
})
