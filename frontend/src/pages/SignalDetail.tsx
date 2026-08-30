import { SignalsFeed } from './SignalsFeed'

/**
 * Alias conservé pour les intégrations qui montent encore le détail directement.
 * Le détail n'est plus une page divergente : il passe par le même workspace,
 * le même feed d'autorisation et les mêmes gardes paywall que `/app/signals/:id`.
 */
export function SignalDetail() {
  return <SignalsFeed />
}
