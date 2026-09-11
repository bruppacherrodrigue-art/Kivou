export function monthLabel(value: string, locale: string): string | null {
  if (!/^\d{4}-\d{2}$/.test(value)) return null
  const parsed = new Date(`${value}-01T00:00:00Z`)
  if (Number.isNaN(parsed.getTime())) return null
  return new Intl.DateTimeFormat(locale === 'fr' ? 'fr-FR' : 'en-GB', {
    month: 'long',
    year: 'numeric',
    timeZone: 'UTC',
  }).format(parsed)
}
