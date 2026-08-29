import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const FOUNDER_API = process.env.KIVOU_FOUNDER_API_PROXY ?? 'http://127.0.0.1:8011'

export default defineConfig({
  root: fileURLToPath(new URL('./founder', import.meta.url)),
  plugins: [react()],
  server: {
    port: 5174,
    proxy: {
      '/api/founder': {
        target: FOUNDER_API,
        changeOrigin: false,
        secure: false,
      },
    },
  },
  build: {
    outDir: fileURLToPath(new URL('./dist-founder', import.meta.url)),
    emptyOutDir: true,
  },
})
