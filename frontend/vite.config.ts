/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Le frontend et l'API partagent une origine en production (https://kivou.eu).
// En développement, le proxy reproduit cette condition : les appels restent
// relatifs, le cookie de session reste `SameSite=Lax` et l'en-tête `Origin`
// envoyé par le navigateur est bien celui que le backend attend. Sans cela,
// `enforce_origin` rejetterait chaque requête modifiante en 403.
const BACKEND = process.env.KIVOU_API_PROXY ?? 'http://127.0.0.1:8000'

const API_PREFIXES = [
  '/auth',
  '/me',
  '/target-icps',
  '/signals',
  '/billing',
  '/notification-preferences',
]

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: Object.fromEntries(
      API_PREFIXES.map((prefix) => [
        prefix,
        { target: BACKEND, changeOrigin: false, secure: false },
      ]),
    ),
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    // jsdom n'évalue pas les media queries : appliquer les feuilles ferait
    // disparaître de l'arbre d'accessibilité tout ce qui est masqué au-dessous
    // d'un point d'arrêt. La fidélité visuelle se vérifie dans un navigateur,
    // pas ici.
    css: false,
    include: ['src/**/*.test.{ts,tsx}'],
  },
})
