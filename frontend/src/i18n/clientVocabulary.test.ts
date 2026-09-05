import { describe, expect, it } from 'vitest'
import { en } from './en'
import { fr } from './fr'

function strings(value: unknown): string[] {
  if (typeof value === 'string') return [value]
  if (Array.isArray(value)) return value.flatMap(strings)
  if (value && typeof value === 'object') return Object.values(value).flatMap(strings)
  return []
}

describe('client vocabulary', () => {
  it('does not expose internal matching language in rendered copy', () => {
    const renderedCopy = strings([fr, en]).join('\n')
    for (const forbidden of [
      'materials_or_components',
      'workforce_capacity',
      '\\bICP\\b',
      'plausible',
      'ciblé',
    ]) {
      expect(renderedCopy).not.toMatch(new RegExp(forbidden, 'iu'))
    }
  })
})
