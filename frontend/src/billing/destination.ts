export function secureBillingDestination(value: string): string | null {
  try {
    const destination = new URL(value)
    if (destination.protocol !== 'https:') return null
    if (destination.username || destination.password) return null
    return destination.href
  } catch {
    return null
  }
}
