import { describe, expect, it, beforeEach } from 'vitest'
import {
  MAXIMUM_SIGNAL_KEY_LENGTH,
  clearCheckoutIntent,
  readCheckoutIntent,
  saveCheckoutIntent,
  validateSignalKey,
} from './checkoutIntent'

/* P0-03 §7 — l'intention d'achat, et ce qu'elle n'est PAS.
 *
 * Ce stockage n'accorde aucun droit. Il ne sert qu'à savoir vers quel signal
 * renvoyer un client APRÈS que le serveur a confirmé son accès. Le
 * déverrouillage reste décidé par `GET /signals/{key}` ; si le serveur répond
 * `locked`, c'est `locked` qui s'affiche, quelle que soit l'intention mémorisée.
 */

beforeEach(() => sessionStorage.clear())

describe('validation de la clé de signal', () => {
  it('accepte une clé ordinaire', () => {
    expect(validateSignalKey('sig_unlocked_1')).toBe('sig_unlocked_1')
  })

  it('refuse ce qui n’est pas une chaîne', () => {
    for (const value of [null, undefined, 42, {}, [], true]) {
      expect(validateSignalKey(value)).toBeNull()
    }
  })

  it('refuse une chaîne vide ou blanche', () => {
    expect(validateSignalKey('')).toBeNull()
    expect(validateSignalKey('   ')).toBeNull()
  })

  it('refuse une clé démesurée', () => {
    expect(validateSignalKey('a'.repeat(MAXIMUM_SIGNAL_KEY_LENGTH))).not.toBeNull()
    expect(validateSignalKey('a'.repeat(MAXIMUM_SIGNAL_KEY_LENGTH + 1))).toBeNull()
  })

  it('refuse tout caractère de contrôle', () => {
    const controls = ['\n', '\r', '\t', String.fromCharCode(0), String.fromCharCode(27)]
    for (const control of controls) {
      expect(validateSignalKey(`sig${control}1`)).toBeNull()
    }
  })

  /* La forme métier d'une clé n'est PAS devinée : l'API en est seule juge, et
   * une expression régulière inventée ici rejetterait demain une clé
   * parfaitement valide. La validation porte sur la sûreté, pas sur le sens. */
  it('ne présume pas de la structure métier de la clé', () => {
    expect(validateSignalKey('9f2c4e8a-1b3d')).not.toBeNull()
    expect(validateSignalKey('568562-2026')).not.toBeNull()
  })
})

describe('cycle de vie de l’intention', () => {
  it('ne rend rien quand rien n’a été mémorisé', () => {
    expect(readCheckoutIntent()).toBeNull()
  })

  it('mémorise puis relit une clé valide', () => {
    saveCheckoutIntent('sig_unlocked_1')
    expect(readCheckoutIntent()).toBe('sig_unlocked_1')
  })

  it('efface ce qui a été mémorisé', () => {
    saveCheckoutIntent('sig_unlocked_1')
    clearCheckoutIntent()
    expect(readCheckoutIntent()).toBeNull()
  })

  it('ne mémorise jamais une clé invalide', () => {
    saveCheckoutIntent(`sig${String.fromCharCode(10)}1`)
    expect(readCheckoutIntent()).toBeNull()
    expect(sessionStorage.length).toBe(0)
  })

  /* Une valeur écrite à la main dans le stockage — ou survivante d'une version
   * précédente — est relue avec la MÊME défiance qu'une entrée réseau. */
  it('refuse une valeur corrompue trouvée dans le stockage', () => {
    saveCheckoutIntent('sig_unlocked_1')
    const key = sessionStorage.key(0)!
    sessionStorage.setItem(key, 'a'.repeat(MAXIMUM_SIGNAL_KEY_LENGTH + 10))
    expect(readCheckoutIntent()).toBeNull()
  })

  it('n’écrit que la clé, et rien du signal', () => {
    saveCheckoutIntent('sig_unlocked_1')
    const stored = JSON.stringify(sessionStorage)
    for (const forbidden of [
      'Constructions Bertrand',
      'Réfection',
      '1240000',
      'boamp',
      'icp_1',
    ]) {
      expect(stored).not.toContain(forbidden)
    }
  })

  it('survit à un stockage indisponible sans casser le parcours', () => {
    // Navigation privée stricte : `sessionStorage` peut lever. Perdre le retour
    // au signal est acceptable ; casser le paiement ne l'est pas.
    const original = Storage.prototype.setItem
    Storage.prototype.setItem = () => {
      throw new DOMException('QuotaExceededError')
    }
    expect(() => saveCheckoutIntent('sig_unlocked_1')).not.toThrow()
    Storage.prototype.setItem = original
    expect(readCheckoutIntent()).toBeNull()
  })
})
