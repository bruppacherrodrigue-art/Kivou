import { useEffect, useRef, useState } from 'react'

/** Refresh only the idle catalogue; never invalidate a commercial's open dossier. */
export function useCatalogueRefresh(enabled: boolean) {
  const [version, setVersion] = useState(0)
  const last = useRef(Number.NEGATIVE_INFINITY)
  useEffect(() => {
    if (!enabled) return
    const refresh = () => {
      if (document.visibilityState !== 'visible'
        || document.activeElement?.matches('input, textarea, select, [contenteditable="true"]')
        || Date.now() - last.current < 1_000) return
      last.current = Date.now()
      setVersion((value) => value + 1)
    }
    const interval = window.setInterval(refresh, 60_000)
    window.addEventListener('focus', refresh)
    document.addEventListener('visibilitychange', refresh)
    return () => {
      window.clearInterval(interval)
      window.removeEventListener('focus', refresh)
      document.removeEventListener('visibilitychange', refresh)
    }
  }, [enabled])
  return version
}
