import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// `npm run build` writes into the Python package, so `./strata360 serve` serves the built app.
// `npm run dev` runs the dev server with hot reload and proxies /api to a running `./strata360 serve` (port 8360).
export default defineConfig({
  base: './',       // relative asset paths, so the app works at the server's root and behind a reverse proxy at a path (api.ts BASE does the same for the API)
  plugins: [react(), tailwindcss()],
  build: { outDir: '../src/strata360/server/static', emptyOutDir: true },
  server: { proxy: { '/api': 'http://127.0.0.1:8360' } },
})
