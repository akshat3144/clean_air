import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The console talks to the FastAPI service for anything computed on demand.
// In dev it is proxied under /api so the browser sees one origin and CORS never
// enters the picture; in production VITE_API_BASE points at the deployed API.
// Either way the app never has a hostname compiled into it.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: process.env.VITE_API_TARGET ?? 'http://127.0.0.1:8000',
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api/, ''),
      },
    },
  },
})
