import type { Money } from '../api/types'
import type { Locale } from '../i18n'
import { normalCasePlace } from '../presentation/locationText'
import type { Dossier, NoticeDuration, ProspectingSignal } from './models'

export function formatAmount(money: Money | null | undefined, locale: Locale): string | null {
  if (!money || !/^\d+(?:\.\d+)?$/.test(money.value) || !/^[A-Z]{3}$/.test(money.currency)) return null
  const [whole, tail = ''] = money.value.split('.')
  const fraction = tail.replace(/0+$/, '')
  const formatter = new Intl.NumberFormat(locale === 'fr' ? 'fr-FR' : 'en-GB', {
    style: 'currency', currency: money.currency, minimumFractionDigits: 0, maximumFractionDigits: 0,
  })
  const parts = formatter.formatToParts(BigInt(whole))
  const lastInteger = parts.map((part) => part.type).lastIndexOf('integer')
  return parts.map((part, index) => part.value + (fraction && index === lastInteger ? `${locale === 'fr' ? ',' : '.'}${fraction}` : '')).join('').replace(/[\u202f\u2009]/g, '\u00a0')
}

export function durationLabel(duration: NoticeDuration, locale: Locale): string {
  const units = locale === 'fr'
    ? { DAY: 'jour', WEEK: 'semaine', MONTH: 'mois', YEAR: 'an' }
    : { DAY: 'day', WEEK: 'week', MONTH: 'month', YEAR: 'year' }
  const plural = duration.value !== '1' && !(locale === 'fr' && duration.unit === 'MONTH') ? 's' : ''
  return `${duration.value.replace('.', locale === 'fr' ? ',' : '.')} ${units[duration.unit]}${plural}`
}

export function safeExternal(value: string | null | undefined): string | null {
  if (!value) return null
  try {
    const url = new URL(value)
    return url.protocol === 'https:' && !url.username && !url.password ? url.toString() : null
  } catch { return null }
}

export function signalTitle(item: ProspectingSignal): string {
  return item.notice_facts?.title || item.factual_display.object_short || item.contract.lot_title || item.contract.title || item.factual_display.headline
}

export function signalClock(item: ProspectingSignal, locale: Locale): { label: string; value: string | null } {
  const dates = item.contract.dates
  if (dates.award) return { label: locale === 'fr' ? 'Attribué le' : 'Awarded on', value: dates.award }
  if (dates.contract_notification) return { label: locale === 'fr' ? 'Notifié le' : 'Notified on', value: dates.contract_notification }
  if (item.notice_facts?.publication_date) return { label: locale === 'fr' ? 'Avis publié le' : 'Notice published on', value: item.notice_facts.publication_date }
  return { label: locale === 'fr' ? 'Publié le' : 'Published on', value: dates.publication }
}

export function signalPlace(item: ProspectingSignal): string | null {
  const place = item.contract.location
  const locality = normalCasePlace(place?.locality)
  const subdivision = normalCasePlace(place?.subdivision_label)
  if (locality && subdivision && locality !== subdivision) return `${locality} (${subdivision})`
  return locality || subdivision || null
}

export function dossierName(profile: Dossier): string {
  return 'official_identity' in profile ? profile.official_identity.name : profile.directory.name
}

export function initials(name: string): string {
  return name.trim().split(/\s+/).slice(0, 2).map((word) => word[0]).join('').toLocaleUpperCase('fr-FR')
}
