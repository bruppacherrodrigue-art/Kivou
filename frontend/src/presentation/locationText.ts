const LOWERCASE_WORDS = new Set([
  'a', 'au', 'aux', 'd', 'de', 'des', 'du', 'en', 'et', 'l', 'la', 'le', 'les', 'sous', 'sur',
])

function folded(value: string): string {
  return value.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase('fr-FR')
}

/** Rend les localités issues des registres lisibles sans modifier la donnée source. */
export function normalCasePlace(value: string | null | undefined): string | null {
  const clean = value?.trim().replace(/\s+/g, ' ')
  if (!clean) return null

  let wordIndex = 0
  return clean.split(/([\s'’-]+)/u).map((part) => {
    if (!part || /^[\s'’-]+$/u.test(part)) return part
    const lower = part.toLocaleLowerCase('fr-FR')
    const keepLower = wordIndex > 0 && LOWERCASE_WORDS.has(folded(lower))
    wordIndex += 1
    return keepLower
      ? lower
      : lower.replace(/^\p{L}/u, (letter) => letter.toLocaleUpperCase('fr-FR'))
  }).join('')
}

/** Les agrégats nationaux ne sont jamais présentés comme un lieu. */
export function visiblePlaceName(value: string | null | undefined): string | null {
  const place = normalCasePlace(value)
  if (!place) return null
  const candidate = folded(place)
  if (new Set([
    'territoire metropolitain',
    'france metropolitaine',
    'comm',
    'commune',
    'decp',
    'dept',
    'departement',
    'reg',
    'region',
    'pays',
  ]).has(candidate)) return null
  if (candidate.includes('boamp') || candidate.includes('decp')) return null
  if (/^(?:(?:[a-z]{2,4}[- ]?)?\d{2,8}|[a-z]{2}\d[a-z0-9]{2,5})$/i.test(place)) return null
  return place
}
