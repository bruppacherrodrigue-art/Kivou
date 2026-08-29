import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
// CLOSEOUT §2 — livraison des polices au BUILD, pas au runtime.
//
// Ces deux paquets (SIL OFL 1.1) embarquent les fichiers `.woff2` variables.
// Vite les résout à la construction, les copie dans `dist/assets` avec une
// empreinte de contenu et réécrit les `@font-face` : la page ne fait donc
// AUCUNE requête vers un tiers, et le rendu ne dépend pas de ce qui est
// installé sur le poste du visiteur.
//
// Les fichiers de police ne sont pas committés : ils viennent d'une dépendance
// npm verrouillée, ce que le manifeste d'assets autorise et qu'un binaire
// déposé dans le dépôt ne permettrait pas.
//
// Seule la variante `wght` (droite) est importée : le design system n'emploie
// aucune italique, et l'importer doublerait le poids téléchargé pour rien.
import '@fontsource-variable/lora/wght.css'
import '@fontsource-variable/instrument-sans/wght.css'
import './styles/tokens.css'
import './reference/public/public-reference.css'
import './reference/dashboard/dashboard-reference.css'
import './styles/reference-surface-isolation.css'
import { App } from './App'

const container = document.getElementById('root')
if (!container) throw new Error('élément racine introuvable')

createRoot(container).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
)
