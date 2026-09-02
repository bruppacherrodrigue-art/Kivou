import { describe, expect, it } from 'vitest'
import { renderHook } from '@testing-library/react'
import type { ReactNode } from 'react'
import { I18nProvider, useI18n, withRenderableSpaces } from './index'

const wrapper = ({ children }: { children: ReactNode }) => <I18nProvider initialLocale="fr">{children}</I18nProvider>

describe('formatage des montants', () => {
  it('ne laisse jamais une espace fine que les polices auto-hébergées ne rendent pas', () => {
    const { result } = renderHook(() => useI18n(), { wrapper })
    for (const text of [result.current.amount('5338215.00', 'EUR')!, result.current.money(533821500, 'chf'), result.current.number(5338215)]) {
      expect(text).not.toMatch(/[\u202F\u2009]/)
      expect(text.replace(/\u00A0/g, ' ')).toContain('5 338 215')
    }
  })

  it('remplace U+202F et U+2009 par une espace insécable ordinaire', () => {
    expect(withRenderableSpaces('5\u202F338\u2009215')).toBe('5\u00A0338\u00A0215')
  })
})