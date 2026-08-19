/* Les quatre illustrations modulaires de la planche 07, RECRÉÉES.
 *
 * Le manifeste d'assets est explicite : « ne pas découper ces assets depuis une
 * maquette d'écran ; recréer des originaux propres avec la même direction
 * artistique ». Leur géométrie — arc, escalier, radar concentrique, arche,
 * porte, marches — est entièrement descriptible en primitives vectorielles :
 * la recréation ne perd rien de la direction approuvée et pèse deux ordres de
 * grandeur de moins qu'un découpage raster.
 *
 * Vocabulaire imposé et respecté : arches, escaliers, portiques, radar,
 * documents, pierre claire, marbre vert, laiton. Aucun personnage, aucun
 * robot, aucun cerveau, aucun blob 3D.
 *
 * Chaque illustration est DÉCORATIVE : elle accompagne un titre et un texte qui
 * portent déjà le sens. Elle est donc marquée `aria-hidden`, ce qui vaut mieux
 * qu'un texte alternatif qui répéterait le titre juste au-dessus (§38).
 */

const STONE = 'var(--kivou-bg-beige)'
const STONE_LIGHT = 'var(--kivou-bg-subtle)'
const MARBLE = 'var(--kivou-action-primary)'
const BRASS = 'var(--kivou-action-accent)'
const LINE = 'var(--kivou-border)'
const TERRACOTTA = 'var(--kivou-color-terracotta)'

interface IllustrationProps {
  className?: string
}

/** Marches de travertin, réutilisées par trois des quatre illustrations. */
function Stairs({ x, y, step = 14 }: { x: number; y: number; step?: number }) {
  return (
    <g>
      {[0, 1, 2, 3].map((index) => (
        <rect
          key={index}
          x={x + index * step}
          y={y - index * step}
          width={step * (4 - index)}
          height={step}
          fill={index % 2 === 0 ? STONE : STONE_LIGHT}
          stroke={LINE}
          strokeWidth="1"
        />
      ))}
    </g>
  )
}

/** 1 — Signal détecté : radar laiton, arc de pierre, marches de marbre vert. */
export function SignalDetectedIllustration({ className }: IllustrationProps) {
  return (
    <svg viewBox="0 0 320 200" className={className} aria-hidden="true" focusable="false">
      <path d="M40 180 A 90 90 0 0 1 130 90 L 130 180 Z" fill={STONE} />
      <path d="M196 180 A 74 74 0 0 1 270 106 L 270 180 Z" fill={MARBLE} opacity="0.92" />
      <g stroke={BRASS} fill="none" strokeWidth="1.1">
        <circle cx="196" cy="86" r="58" opacity="0.35" />
        <circle cx="196" cy="86" r="40" opacity="0.5" />
        <circle cx="196" cy="86" r="22" opacity="0.7" />
        <line x1="118" y1="86" x2="274" y2="86" strokeWidth="1" opacity="0.6" />
        <line x1="196" y1="18" x2="196" y2="158" strokeWidth="1" opacity="0.6" />
      </g>
      <circle cx="196" cy="86" r="7" fill={BRASS} />
      <circle cx="238" cy="118" r="5.5" fill={MARBLE} />
      <g opacity="0.55">
        {[0, 1, 2, 3, 4].map((row) =>
          [0, 1, 2, 3, 4].map((col) => (
            <circle
              key={`${row}-${col}`}
              cx={48 + col * 9}
              cy={140 + row * 9}
              r="1.2"
              fill={BRASS}
            />
          )),
        )}
      </g>
      <Stairs x={224} y={166} />
    </svg>
  )
}

/** 2 — Preuve documentaire : feuillets sur socle de pierre, cachet de contrôle. */
export function DocumentEvidenceIllustration({ className }: IllustrationProps) {
  return (
    <svg viewBox="0 0 320 200" className={className} aria-hidden="true" focusable="false">
      <path d="M250 24 L 300 24 L 300 176 L 250 176 Z" fill={STONE} />
      <g stroke={LINE} strokeWidth="1">
        {[262, 274, 286].map((x) => (
          <line key={x} x1={x} y1="24" x2={x} y2="176" />
        ))}
      </g>
      <path d="M150 62 A 62 62 0 0 1 212 124 L 212 176 L 150 176 Z" fill={MARBLE} opacity="0.9" />
      <rect x="52" y="150" width="188" height="26" fill={STONE} stroke={LINE} strokeWidth="1" />
      <g transform="rotate(-6 130 96)">
        <rect x="86" y="44" width="92" height="112" rx="4" fill={STONE_LIGHT} stroke={LINE} />
      </g>
      <rect
        x="106"
        y="38"
        width="98"
        height="118"
        rx="4"
        fill="var(--kivou-bg-surface)"
        stroke={LINE}
      />
      <g stroke={LINE} strokeWidth="4" strokeLinecap="round" opacity="0.75">
        {[66, 80, 94, 108, 122].map((y, index) => (
          <line key={y} x1="122" y1={y} x2={index % 2 === 0 ? 178 : 162} y2={y} />
        ))}
      </g>
      <circle cx="188" cy="58" r="13" fill="none" stroke={BRASS} strokeWidth="1.4" />
      <path
        d="M182 58 l4.5 4.5 L 195 53"
        fill="none"
        stroke={BRASS}
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <rect
        x="42"
        y="106"
        width="72"
        height="46"
        rx="4"
        fill="var(--kivou-bg-surface)"
        stroke={LINE}
      />
      <polyline
        points="52,142 68,128 82,134 104,114"
        fill="none"
        stroke={BRASS}
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

/** 3 — Aucun signal pertinent : arche ouverte, croix laiton, escalier. */
export function NoSignalIllustration({ className }: IllustrationProps) {
  return (
    <svg viewBox="0 0 320 200" className={className} aria-hidden="true" focusable="false">
      <path
        d="M96 176 L 96 96 A 64 64 0 0 1 224 96 L 224 176 L 200 176 L 200 96 A 40 40 0 0 0 120 96 L 120 176 Z"
        fill={STONE}
        stroke={LINE}
        strokeWidth="1"
      />
      <path d="M232 176 A 54 54 0 0 1 286 122 L 286 176 Z" fill={MARBLE} opacity="0.9" />
      <g stroke={LINE} strokeWidth="1" opacity="0.8">
        {[240, 252, 264].map((x) => (
          <line key={x} x1={x} y1="72" x2={x} y2="176" />
        ))}
      </g>
      <circle cx="160" cy="104" r="30" fill="none" stroke={BRASS} strokeWidth="1.2" opacity="0.8" />
      <g stroke={BRASS} strokeWidth="2.4" strokeLinecap="round">
        <line x1="149" y1="93" x2="171" y2="115" />
        <line x1="171" y1="93" x2="149" y2="115" />
      </g>
      <Stairs x={34} y={166} />
    </svg>
  )
}

/** 4 — Paiement confirmé / accès activé : porte de marbre vert, symbole radial,
 *  marches de travertin, sphère laiton. */
export function PaymentConfirmedIllustration({ className }: IllustrationProps) {
  return (
    <svg viewBox="0 0 320 200" className={className} aria-hidden="true" focusable="false">
      <path d="M40 176 A 46 46 0 0 1 86 130 L 86 176 Z" fill={TERRACOTTA} opacity="0.85" />
      <path
        d="M106 176 L 106 88 A 54 54 0 0 1 214 88 L 214 176 Z"
        fill={STONE}
        stroke={LINE}
        strokeWidth="1"
      />
      <path d="M122 176 L 122 90 A 38 38 0 0 1 198 90 L 198 176 Z" fill={MARBLE} />
      <g
        stroke={BRASS}
        strokeWidth="1.6"
        strokeLinecap="round"
        fill="none"
        transform="translate(160 108) scale(0.42) translate(-50 -50)"
      >
        <line x1="62" y1="50" x2="81" y2="50" />
        <line x1="58.49" y1="58.49" x2="71.92" y2="71.92" />
        <line x1="50" y1="62" x2="50" y2="81" />
        <line x1="41.51" y1="58.49" x2="28.08" y2="71.92" />
        <line x1="38" y1="50" x2="19" y2="50" />
        <line x1="41.51" y1="41.51" x2="28.08" y2="28.08" />
        <line x1="50" y1="38" x2="50" y2="19" />
        <line x1="58.49" y1="41.51" x2="71.92" y2="28.08" />
      </g>
      <g fill={STONE} stroke={LINE} strokeWidth="1">
        <rect x="96" y="176" width="128" height="12" />
        <rect x="84" y="164" width="152" height="12" fill={STONE_LIGHT} />
      </g>
      <path d="M244 176 A 48 48 0 0 1 292 128 L 292 176 Z" fill={STONE} />
      <g stroke={LINE} strokeWidth="1" opacity="0.8">
        {[254, 266, 278].map((x) => (
          <line key={x} x1={x} y1="86" x2={x} y2="176" />
        ))}
      </g>
      <circle cx="80" cy="160" r="14" fill={BRASS} opacity="0.9" />
    </svg>
  )
}

/* L'arche architecturale du hero : escalier courbe, pierre, marbre vert.
 *
 * La composition reprend les références 01/02/03, où la matière occupe la
 * colonne droite en desktop et le bas de section en mobile. Les DEUX textures
 * photographiques appelées par le manifeste (travertin seamless, marbre vert)
 * ne sont pas fournies dans le pack ; elles ne sont pas remplacées par de
 * l'imagerie de substitution, ce que §39 interdit. La composition est donc
 * rendue en dégradés minéraux issus de la palette approuvée, ce qui préserve la
 * géométrie et le rapport de valeurs sans inventer une photographie.
 */
export function ArchitecturalHero({ className }: IllustrationProps) {
  return (
    <svg
      viewBox="0 0 640 520"
      className={className}
      aria-hidden="true"
      focusable="false"
      preserveAspectRatio="xMidYMid slice"
    >
      <defs>
        <linearGradient id="kivou-stone" x1="0" y1="0" x2="0.7" y2="1">
          <stop offset="0%" stopColor="#f6f0e7" />
          <stop offset="52%" stopColor="#e6dccd" />
          <stop offset="100%" stopColor="#cfc2ae" />
        </linearGradient>
        <linearGradient id="kivou-marble" x1="0.1" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#2f5947" />
          <stop offset="55%" stopColor="#1f3c30" />
          <stop offset="100%" stopColor="#152a22" />
        </linearGradient>
        <linearGradient id="kivou-wall" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stopColor="#ede5d9" />
          <stop offset="100%" stopColor="#dbcfbc" />
        </linearGradient>
        <clipPath id="kivou-hero-clip">
          <rect x="0" y="0" width="640" height="520" rx="18" />
        </clipPath>
      </defs>

      <g clipPath="url(#kivou-hero-clip)">
        <rect width="640" height="520" fill="url(#kivou-stone)" />

        {/* Paroi cannelée à droite — la lumière rasante des références. */}
        <rect x="452" y="0" width="188" height="520" fill="url(#kivou-wall)" />
        <g stroke="#c9bba6" strokeWidth="1" opacity="0.55">
          {[470, 492, 514, 536, 558, 580, 602, 624].map((x) => (
            <line key={x} x1={x} y1="0" x2={x} y2="520" />
          ))}
        </g>

        {/* L'arche de pierre : métaphore d'accès et de progression. */}
        <path
          d="M96 520 L 96 232 A 148 148 0 0 1 392 232 L 392 520 L 344 520 L 344 236 A 100 100 0 0 0 144 236 L 144 520 Z"
          fill="#f1eae0"
          stroke="#d9cdba"
          strokeWidth="1"
        />

        {/* La masse de marbre vert, signature de la direction approuvée. Elle
            est ancrée en bas à droite et assez large pour tenir le contraste
            même lorsque le cadre est rogné par `slice`. */}
        <path d="M640 520 A 400 400 0 0 0 240 520 Z" fill="url(#kivou-marble)" />

        {/* Veines de laiton, très discrètes. */}
        <g stroke={BRASS} strokeWidth="0.8" fill="none" opacity="0.28">
          <path d="M300 512 C 350 430 400 384 500 352" />
          <path d="M360 518 C 404 456 470 420 560 404" />
          <path d="M430 516 C 462 472 512 448 604 440" />
        </g>

        {/* L'escalier courbe, en travertin clair, posé devant la masse verte. */}
        <g>
          {[0, 1, 2, 3, 4, 5, 6].map((index) => (
            <rect
              key={index}
              x={128 + index * 24}
              y={468 - index * 28}
              width={268 - index * 24}
              height="28"
              fill={index % 2 === 0 ? '#f4ede2' : '#e7ddcc'}
              stroke="#d6c9b6"
              strokeWidth="0.9"
            />
          ))}
        </g>
      </g>
    </svg>
  )
}
