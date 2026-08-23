/* Un jeu d'icônes minimal : trait fin, géométrique, monochrome.
 *
 * Aucune bibliothèque n'est ajoutée pour une quinzaine de glyphes. Toutes
 * héritent de `currentColor` et sont décoratives — le nom accessible vient
 * toujours du texte qui les accompagne, jamais de l'icône elle-même.
 */
import type { SVGProps } from 'react'

type IconProps = SVGProps<SVGSVGElement>

function Icon({ children, ...props }: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      {...props}
    >
      {children}
    </svg>
  )
}

/** Dashboard — quatre surfaces d’action, sans suggérer une métrique. */
export const DashboardIcon = (props: IconProps) => (
  <Icon {...props}>
    <rect x="3.5" y="3.5" width="7" height="7" rx="1.5" />
    <rect x="13.5" y="3.5" width="7" height="4" rx="1.5" />
    <rect x="3.5" y="13.5" width="7" height="7" rx="1.5" />
    <rect x="13.5" y="10.5" width="7" height="10" rx="1.5" />
  </Icon>
)

/** Signaux — le radar, écho direct du symbole de marque. */
export const SignalsIcon = (props: IconProps) => (
  <Icon {...props}>
    <circle cx="12" cy="12" r="2.5" />
    <path d="M7.8 16.2a6 6 0 0 1 0-8.4" />
    <path d="M16.2 7.8a6 6 0 0 1 0 8.4" />
    <path d="M5 19a10 10 0 0 1 0-14" />
    <path d="M19 5a10 10 0 0 1 0 14" />
  </Icon>
)

/** Profils de ciblage — la cible. */
export const TargetIcon = (props: IconProps) => (
  <Icon {...props}>
    <circle cx="12" cy="12" r="8.5" />
    <circle cx="12" cy="12" r="4.5" />
    <circle cx="12" cy="12" r="1" fill="currentColor" />
  </Icon>
)

export const BillingIcon = (props: IconProps) => (
  <Icon {...props}>
    <rect x="2.5" y="5.5" width="19" height="13" rx="2.5" />
    <path d="M2.5 10h19" />
    <path d="M6 14.5h3.5" />
  </Icon>
)

export const BellIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M18 9a6 6 0 1 0-12 0c0 4.5-1.5 5.5-2 6.5h16c-.5-1-2-2-2-6.5" />
    <path d="M10 19a2.2 2.2 0 0 0 4 0" />
  </Icon>
)

export const LogoutIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M14.5 4.5H6a1.5 1.5 0 0 0-1.5 1.5v12A1.5 1.5 0 0 0 6 19.5h8.5" />
    <path d="M17 8.5 20.5 12 17 15.5" />
    <path d="M20.5 12h-10" />
  </Icon>
)

export const ArrowRightIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M4.5 12h15" />
    <path d="M14 6.5 19.5 12 14 17.5" />
  </Icon>
)

export const ExternalIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M14 4.5h5.5V10" />
    <path d="M19.5 4.5 11 13" />
    <path d="M18 14v5.5H4.5V6H10" />
  </Icon>
)

export const CheckIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M5 12.5 9.5 17 19 7" />
  </Icon>
)

export const ChevronDownIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M6 9.5 12 15.5 18 9.5" />
  </Icon>
)

export const DocumentIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M13.5 3.5H7A1.5 1.5 0 0 0 5.5 5v14A1.5 1.5 0 0 0 7 20.5h10a1.5 1.5 0 0 0 1.5-1.5V8.5Z" />
    <path d="M13.5 3.5v5h5" />
    <path d="M9 13h6" />
    <path d="M9 16.5h4" />
  </Icon>
)

export const ClockIcon = (props: IconProps) => (
  <Icon {...props}>
    <circle cx="12" cy="12" r="8.5" />
    <path d="M12 7.5V12l3 1.8" />
  </Icon>
)

export const BuildingIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M4.5 20.5V6l7-2.5V20.5" />
    <path d="M11.5 9.5h8v11" />
    <path d="M3 20.5h18" />
    <path d="M7.5 9h1M7.5 13h1M15 13h1M15 16.5h1" />
  </Icon>
)

export const NeedIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M9.5 18h5" />
    <path d="M10 21h4" />
    <path d="M12 3a6 6 0 0 0-3.5 10.9c.6.5.9 1.2 1 1.9h5c.1-.7.4-1.4 1-1.9A6 6 0 0 0 12 3Z" />
  </Icon>
)

export const LockIcon = (props: IconProps) => (
  <Icon {...props}>
    <rect x="4.5" y="10.5" width="15" height="9.5" rx="2" />
    <path d="M8 10.5V7.5a4 4 0 0 1 8 0v3" />
  </Icon>
)

export const MenuIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M4 7h16" />
    <path d="M4 12h16" />
    <path d="M4 17h16" />
  </Icon>
)

export const CloseIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M6 6l12 12" />
    <path d="M18 6 6 18" />
  </Icon>
)

export const ShieldIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M12 3.5 19 6v6c0 4-3 7-7 8.5C8 19 5 16 5 12V6Z" />
    <path d="M9 12l2 2 4-4" />
  </Icon>
)

export const MapPinIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M12 21s6.5-5.5 6.5-10a6.5 6.5 0 1 0-13 0C5.5 15.5 12 21 12 21Z" />
    <circle cx="12" cy="11" r="2.5" />
  </Icon>
)
