import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

/* CLOSEOUT §2 — la livraison des polices est un contrat, pas un détail.
 *
 * Lora et Instrument Sans PORTENT la direction éditoriale approuvée : le serif
 * pour la promesse, le sans-serif pour la décision et la donnée. Si leur
 * livraison disparaît, l'interface retombe silencieusement sur Georgia et Arial
 * — elle reste lisible, donc personne ne le remarque, et le design system n'est
 * plus respecté.
 *
 * Ces vérifications échouent bruyamment si l'une des quatre pièces du montage
 * est retirée : les paquets, l'import, les piles de tokens, ou l'absence de
 * tiers.
 */

const root = join(process.cwd())
const read = (path: string) => readFileSync(join(root, path), 'utf8')

const FONT_PACKAGES = [
  '@fontsource-variable/lora',
  '@fontsource-variable/instrument-sans',
] as const

describe('livraison des polices', () => {
  it('déclare les deux paquets de police comme dépendances de production', () => {
    const manifest = JSON.parse(read('package.json')) as {
      dependencies: Record<string, string>
    }

    for (const name of FONT_PACKAGES) {
      // En `dependencies`, pas en `devDependencies` : ce sont des entrées de
      // BUILD, et une installation de production doit les avoir.
      expect(manifest.dependencies, `${name} doit être une dépendance`).toHaveProperty(name)
    }
  })

  it('importe les feuilles de police dans le point d’entrée', () => {
    const main = read('src/main.tsx')

    for (const name of FONT_PACKAGES) {
      expect(main).toContain(`${name}/wght.css`)
    }

    expect(main).toContain("'./styles/tokens.css'")
    expect(main).not.toContain("'./styles/global.css'")
    expect(main).toContain("'./presentation/public/marketing.css'")
    expect(main).toContain("'./presentation/dashboard/app-shell.css'")
  })

  it('nomme les familles réellement livrées en tête des piles de tokens', () => {
    const tokens = read('src/styles/tokens.css')

    // Les `@font-face` de Fontsource déclarent « … Variable » : c'est ce nom-là
    // qui désigne le fichier téléchargé. Sans lui en tête, la pile ne
    // sélectionnerait jamais la police livrée.
    expect(tokens).toMatch(/--kivou-font-display:\s*'Lora Variable'/)
    expect(tokens).toMatch(/--kivou-font-sans:\s*\n?\s*'Instrument Sans Variable'/)

    // Les substituts restent présents : ils ne servent qu'en cas d'échec.
    expect(tokens).toContain('serif')
    expect(tokens).toContain('sans-serif')
  })

  it('ne demande aucune police à un tiers', () => {
    const html = read('index.html')
    const tokens = read('src/styles/tokens.css')
    const global = read('src/styles/global.css')

    for (const source of [html, tokens, global]) {
      for (const host of [
        'fonts.googleapis.com',
        'fonts.gstatic.com',
        'use.typekit.net',
        'fonts.bunny.net',
        'cdn.jsdelivr.net',
      ]) {
        expect(source).not.toContain(host)
      }
    }
  })

  it('n’embarque aucun fichier de police dans le dépôt', () => {
    // Le manifeste d'assets interdit de committer des binaires de police. Ils
    // viennent d'une dépendance npm verrouillée, jamais de `public/`.
    const html = read('index.html')
    expect(html).not.toMatch(/\.(woff2?|ttf|otf|eot)/i)
  })
})
