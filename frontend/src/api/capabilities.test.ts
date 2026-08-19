import { describe, expect, it } from 'vitest'
import { MVP_TERRITORIES, MVP_TERRITORY_CODES, MVP_THRESHOLD_CURRENCIES } from './capabilities'

/* CLOSEOUT §4 — la liste de territoires est une décision produit, épinglée.
 *
 * Ces tests ne défendent pas un nombre magique : ils défendent le fait que la
 * liste soit DÉLIBÉRÉE. Un ajout ou un retrait doit faire échouer ce fichier,
 * pour que le changement de périmètre soit revu plutôt que constaté après coup
 * par un client dont le flux est resté vide.
 */

describe('territoires du MVP', () => {
  it('propose exactement les dix territoires décidés pour le MVP', () => {
    expect(MVP_TERRITORY_CODES).toEqual([
      'FR',
      'CH',
      'BE',
      'DE',
      'IT',
      'ES',
      'LU',
      'NL',
      'AT',
      'PT',
    ])
  })

  it('n’emploie que des codes ISO 3166-1 alpha-2 en majuscules', () => {
    // C'est la forme que `TargetIcpInput.territories` attend ; une minuscule ou
    // un nom de pays ne serait jamais mis en correspondance.
    for (const code of MVP_TERRITORY_CODES) {
      expect(code).toMatch(/^[A-Z]{2}$/)
    }
  })

  it('ne répète aucun territoire', () => {
    expect(new Set(MVP_TERRITORY_CODES).size).toBe(MVP_TERRITORY_CODES.length)
  })

  it('traduit chaque territoire dans les deux langues', () => {
    for (const territory of MVP_TERRITORIES) {
      expect(territory.fr.length).toBeGreaterThan(0)
      expect(territory.en.length).toBeGreaterThan(0)
    }
  })

  it('propose les deux devises que Kivou facture', () => {
    expect(MVP_THRESHOLD_CURRENCIES).toEqual(['EUR', 'CHF'])
  })
})
