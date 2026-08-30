const listeners = new Set<() => void>()

export function notifyTargetIcpChanged() {
  for (const listener of listeners) listener()
}

export function subscribeToTargetIcpChanges(listener: () => void) {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}
