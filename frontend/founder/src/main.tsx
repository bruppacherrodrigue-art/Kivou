import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import '@fontsource-variable/lora/wght.css'
import '@fontsource-variable/instrument-sans/wght.css'
import { FounderApp } from './FounderApp'
import './styles.css'

const container = document.getElementById('founder-root')
if (!container) throw new Error('élément racine Founder Console introuvable')

createRoot(container).render(
  <StrictMode>
    <FounderApp />
  </StrictMode>,
)
