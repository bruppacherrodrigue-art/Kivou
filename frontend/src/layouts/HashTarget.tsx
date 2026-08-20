import { useEffect } from 'react'
import { useLocation } from 'react-router-dom'

/* Faire fonctionner `/#comment` et `/#tarifs`, pour de vrai.
 *
 * Ce que le routeur ne fait pas à notre place
 * ───────────────────────────────────────────
 * Un `<Link to="/#tarifs">` change l'URL, mais React Router ne défile pas vers
 * l'ancre et ne déplace pas le focus. Depuis la page d'accueil, le navigateur
 * ne fait rien non plus : il n'y a pas eu de chargement de document. Et depuis
 * `/exemple-de-signal`, la cible n'existe même pas encore au moment où l'URL
 * change — la page d'accueil doit d'abord être montée.
 *
 * D'où ce composant : il attend que la cible existe, puis l'amène à l'écran ET
 * lui donne le focus. Défiler sans déplacer le focus laisserait un utilisateur
 * au clavier au sommet du document, à lire une section qu'il ne peut pas
 * atteindre en tabulant.
 *
 * Le focus va sur la SECTION, qui porte `tabIndex={-1}` : focusable par
 * programme, jamais dans l'ordre de tabulation naturel.
 */
export function HashTarget() {
  const { hash, key } = useLocation()

  useEffect(() => {
    if (!hash) return
    const id = hash.slice(1)

    // La cible peut n'être montée qu'au rendu suivant, quand on arrive d'une
    // autre page. Deux images suffisent ; au-delà, l'ancre n'existe pas et
    // insister ne servirait à rien.
    let frames = 0
    let raf = 0
    const attempt = () => {
      const target = document.getElementById(id)
      if (target) {
        // Appel défensif : `scrollIntoView` n'existe pas partout (jsdom, très
        // vieux navigateurs). Son absence ne doit pas empêcher le déplacement
        // du focus, qui est la partie ACCESSIBLE du comportement.
        target.scrollIntoView?.({ block: 'start' })
        // `preventScroll` : le défilement a déjà eu lieu ci-dessus, et laisser
        // le focus le refaire produirait un saut visible.
        target.focus({ preventScroll: true })
        return
      }
      if (frames++ < 2) raf = requestAnimationFrame(attempt)
    }
    raf = requestAnimationFrame(attempt)
    return () => cancelAnimationFrame(raf)
    // `key` change à chaque navigation : recliquer la même ancre refonctionne.
  }, [hash, key])

  return null
}
