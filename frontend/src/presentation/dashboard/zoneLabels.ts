export function sharedZoneLabels(profile: { zone_labels?: string[] | null } | null | undefined): string[] {
  return [...new Set((profile?.zone_labels ?? [])
    .map((label) => label.trim())
    .filter(Boolean)
    .map((label) => label === 'FR' ? 'France' : label))]
}
