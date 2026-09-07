import { ApiError } from './client'

export function validEmail(value: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value.trim())
}

export function emailRequestError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 422) return error.fields.find((field) => field.field === 'email')?.message || 'Indiquez une adresse email valide.'
    if (error.status === 409) return 'Cette adresse ne peut pas être utilisée.'
    if (error.status === 429) return 'Un lien vient déjà d’être demandé. Patientez avant de réessayer.'
  }
  return 'Le lien n’a pas pu être envoyé. Réessayez.'
}
