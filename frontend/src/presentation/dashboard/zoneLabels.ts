export function sharedZoneLabels(profile: { zone_labels?: string[] | null } | null | undefined): string[] {
  return [...new Set((profile?.zone_labels ?? []).filter((label) => label && label !== 'FR'))]
}
