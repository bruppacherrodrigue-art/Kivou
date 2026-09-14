import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import postcss from 'postcss'
import { expect, test } from 'vitest'

test('the unused pre-V11 dashboard module is retired', () => {
  expect(existsSync(resolve(process.cwd(), 'src/pages/Dashboard.module.css'))).toBe(false)
})

test('exclusive old prospecting rules are retired without removing shared profile or public styles', () => {
  const css = postcss.parse(readFileSync(resolve(process.cwd(), 'src/presentation/dashboard/app-shell.css'), 'utf8'))
  const standalone = new Set<string>()
  css.walkRules((rule) => { if (rule.selectors.length === 1) standalone.add(rule.selector) })
  for (const obsolete of ['.overview-main', '.overview-focus-grid', '.overview-awards-card', '.company-list-item', '.company-detail', '.signal-document', '.signal-card-summary', '.workflow-overview-steps']) {
    expect(standalone.has(obsolete), obsolete).toBe(false)
  }
  for (const retained of ['.target-profile-layout', '.primary-action', '.text-link', '.auth-page']) {
    expect(standalone.has(retained), retained).toBe(true)
  }
})
