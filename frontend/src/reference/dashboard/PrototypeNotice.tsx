import { Info } from 'lucide-react'
import type { ReactNode } from 'react'

export function PrototypeNotice({ children }: { children: ReactNode }) {
  return (
    <div className="prototype-notice" role="note">
      <Info aria-hidden="true" />
      <p>{children}</p>
    </div>
  )
}
