import { createContext, useCallback, useContext, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { fr } from './fr'
import type { Dictionary } from './fr'
import { en } from './en'

export type Locale = 'fr' | 'en'

export const LOCALES: readonly Locale[] = ['fr', 'en'] as const

const DICTIONARIES: Record<Locale, Dictionary> = { fr, en }

/** La locale du navigateur, repliée sur le français — la langue par défaut du
 *  backend. Elle ne sert QUE pour les pages publiques : une fois connecté,
 *  `account.locale` fait autorité. */
export function preferredLocale(): Locale {
  if (typeof navigator === 'undefined') return 'fr'
  const langs = navigator.languages?.length ? navigator.languages : [navigator.language]
  for (const raw of langs) {
    const base = (raw ?? '').slice(0, 2).toLowerCase()
    if (base === 'en') return 'en'
    if (base === 'fr') return 'fr'
  }
  return 'fr'
}

/** Substitue `{clé}` par sa valeur. Une clé absente reste littérale plutôt que
 *  de disparaître : un trou visible se corrige, un trou silencieux se propage. */
export function interpolate(template: string, values?: Record<string, string | number>): string {
  if (!values) return template
  return template.replace(/\{(\w+)\}/g, (match, key: string) =>
    key in values ? String(values[key]) : match,
  )
}

/** Choisit la forme singulier/pluriel. Le français et l'anglais partagent la
 *  même règle binaire au-delà de zéro ; aucune bibliothèque n'est justifiée. */
export function plural(count: number, one: string, other: string): string {
  return Math.abs(count) === 1 ? one : other
}

interface I18nValue {
  locale: Locale
  t: Dictionary
  setLocale: (locale: Locale) => void
  /** `Intl.NumberFormat` sur les montants en unités mineures (facturation). */
  money: (minorUnits: number, currency: string) => string
  /** Un montant de contrat tel que l'API le renvoie : une chaîne décimale et
   *  une devise. Formaté dans la locale courante — sans quoi un montant
   *  français s'afficherait avec des séparateurs anglais. */
  amount: (value: string | null | undefined, currency: string | null | undefined) => string | null
  /** `Intl.DateTimeFormat` sur une date ISO. Rend `null` si la date est absente. */
  date: (iso: string | null | undefined) => string | null
  number: (value: number) => string
}

const I18nContext = createContext<I18nValue | null>(null)

const LOCALE_TAGS: Record<Locale, string> = { fr: 'fr-FR', en: 'en-GB' }

export function I18nProvider({
  children,
  initialLocale,
}: {
  children: ReactNode
  initialLocale?: Locale
}) {
  const [locale, setLocaleState] = useState<Locale>(initialLocale ?? preferredLocale())

  const setLocale = useCallback((next: Locale) => {
    setLocaleState(next)
    if (typeof document !== 'undefined') document.documentElement.lang = next
  }, [])

  const value = useMemo<I18nValue>(() => {
    const tag = LOCALE_TAGS[locale]
    return {
      locale,
      t: DICTIONARIES[locale],
      setLocale,
      money: (minorUnits, currency) =>
        new Intl.NumberFormat(tag, {
          style: 'currency',
          currency: currency.toUpperCase(),
          minimumFractionDigits: minorUnits % 100 === 0 ? 0 : 2,
        }).format(minorUnits / 100),
      amount: (value, currency) => {
        if (value === null || value === undefined || !currency) return null
        const numeric = Number(value)
        if (Number.isNaN(numeric)) return `${value} ${currency}`
        return new Intl.NumberFormat(tag, {
          style: 'currency',
          currency: currency.toUpperCase(),
          maximumFractionDigits: 0,
        }).format(numeric)
      },
      date: (iso) => {
        if (!iso) return null
        const parsed = new Date(iso)
        if (Number.isNaN(parsed.getTime())) return null
        return new Intl.DateTimeFormat(tag, {
          year: 'numeric',
          month: 'long',
          day: 'numeric',
        }).format(parsed)
      },
      number: (n) => new Intl.NumberFormat(tag).format(n),
    }
  }, [locale, setLocale])

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>
}

export function useI18n(): I18nValue {
  const value = useContext(I18nContext)
  if (!value) throw new Error('useI18n doit être utilisé dans un I18nProvider')
  return value
}
