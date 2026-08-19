import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { auth } from '../api/endpoints'
import { ApiError, onUnauthenticated } from '../api/client'
import type { Locale, Me } from '../api/types'

/* La session vit ici, et `GET /me` en est la SEULE autorité.
 *
 * Le frontend ne déduit jamais l'authentification d'un état local : un drapeau
 * `isLoggedIn` posé après une connexion réussie survivrait à une session
 * révoquée côté serveur, et laisserait l'application afficher un shell vide
 * pendant que chaque appel échoue en 401.
 */

export type SessionState =
  | { status: 'loading'; me: null }
  | { status: 'authenticated'; me: Me }
  | { status: 'unauthenticated'; me: null; expired: boolean }

interface SessionValue {
  state: SessionState
  /** Relit `/me`. Appelé après une connexion, une inscription, ou un changement
   *  susceptible d'avoir fait avancer l'onboarding. */
  refresh: () => Promise<void>
  /** Remplace l'utilisateur courant sans aller-retour réseau — le corps de
   *  réponse de `/auth/login` et `/auth/signup` EST un `MeResponse`. */
  adopt: (me: Me) => void
  signOut: () => Promise<void>
}

const SessionContext = createContext<SessionValue | null>(null)

export function SessionProvider({
  children,
  initialState,
}: {
  children: ReactNode
  initialState?: SessionState
}) {
  const [state, setState] = useState<SessionState>(initialState ?? { status: 'loading', me: null })
  // Empêche qu'un 401 tardif écrase un état déjà résolu après déconnexion.
  const mounted = useRef(true)

  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])

  const refresh = useCallback(async () => {
    try {
      const me = await auth.me()
      if (mounted.current) setState({ status: 'authenticated', me })
    } catch (error) {
      if (!mounted.current) return
      const expired = error instanceof ApiError && error.isUnauthenticated
      setState({ status: 'unauthenticated', me: null, expired: false })
      // Un échec réseau n'est pas une session expirée : ne pas le dire.
      if (!expired && !(error instanceof ApiError)) throw error
    }
  }, [])

  const adopt = useCallback((me: Me) => {
    setState({ status: 'authenticated', me })
  }, [])

  const signOut = useCallback(async () => {
    try {
      await auth.logout()
    } catch {
      // Une déconnexion qui échoue côté serveur ne doit pas retenir
      // l'utilisateur dans une application à laquelle il n'a plus accès.
    }
    if (mounted.current) setState({ status: 'unauthenticated', me: null, expired: false })
  }, [])

  // La vérification initiale n'est faite qu'une fois, et seulement si aucun
  // état n'a été fourni (les tests en injectent un pour rester déterministes).
  useEffect(() => {
    if (initialState) return
    void refresh()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Un 401 sur n'importe quel appel invalide la session — une seule fois, quel
  // que soit le nombre d'appels concurrents qui ont échoué.
  useEffect(
    () =>
      onUnauthenticated(() => {
        if (!mounted.current) return
        setState((current) =>
          current.status === 'authenticated'
            ? { status: 'unauthenticated', me: null, expired: true }
            : current,
        )
      }),
    [],
  )

  const value = useMemo<SessionValue>(
    () => ({ state, refresh, adopt, signOut }),
    [state, refresh, adopt, signOut],
  )

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
}

export function useSession(): SessionValue {
  const value = useContext(SessionContext)
  if (!value) throw new Error('useSession doit être utilisé dans un SessionProvider')
  return value
}

/** L'utilisateur authentifié, ou une erreur. À n'appeler que sous `RequireAuth`. */
export function useCurrentUser(): Me {
  const { state } = useSession()
  if (state.status !== 'authenticated') {
    throw new Error('useCurrentUser exige une session authentifiée')
  }
  return state.me
}

export function accountLocale(me: Me | null): Locale | undefined {
  if (me?.locale === 'fr' || me?.locale === 'en') return me.locale
  return undefined
}
