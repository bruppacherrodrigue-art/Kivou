import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { useSession } from './SessionProvider'
import { FullPageLoader } from '../components/FullPageLoader'
import type { Me } from '../api/types'

/* Les trois états de session, rendus explicitement.
 *
 * `loading` ne redirige PAS. Traiter « je ne sais pas encore » comme « non
 * connecté » renverrait chaque rechargement de page vers la connexion, puis
 * vers l'application une fois `/me` résolu — l'aller-retour visible que §11
 * appelle une boucle d'authentification.
 */
export function RequireAuth() {
  const { state } = useSession()
  const location = useLocation()

  if (state.status === 'loading') return <FullPageLoader />

  if (state.status === 'unauthenticated') {
    // La destination est mémorisée dans l'état de navigation, jamais dans
    // l'URL : une adresse de retour recopiable est un vecteur de redirection
    // ouverte, et elle n'apporte rien ici.
    return (
      <Navigate
        to="/login"
        replace
        state={{ from: location.pathname + location.search, expired: state.expired }}
      />
    )
  }

  return <Outlet />
}

/** Où va un utilisateur authentifié qui n'a demandé aucune page en
 *  particulier. Un compte sans profil exploitable va à l'onboarding : le feed
 *  lui rendrait un état vide qu'il ne saurait pas résoudre. */
export function homeFor(me: Me): string {
  return me.onboarding_status === 'ready_for_signals' ? '/app/signals' : '/onboarding'
}

/** L'inverse : une page publique d'authentification qu'un utilisateur déjà
 *  connecté n'a aucune raison de voir.
 *
 *  La destination suit `homeFor`. Renvoyer inconditionnellement vers le feed
 *  ferait courir cette redirection contre celle du formulaire de connexion, et
 *  un compte incomplet atterrirait sur un feed vide au lieu de l'onboarding. */
export function RedirectIfAuthenticated() {
  const { state } = useSession()
  if (state.status === 'loading') return <FullPageLoader />
  if (state.status === 'authenticated') return <Navigate to={homeFor(state.me)} replace />
  return <Outlet />
}
