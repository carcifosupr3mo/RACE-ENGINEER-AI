import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Build output is served by the FastAPI backend at /app/ (same backend for web and desktop shell).
export default defineConfig({
  plugins: [react()],
  base: '/app/',
  build: { outDir: '../backend/race_engineer/api/webdist', emptyOutDir: true, chunkSizeWarningLimit: 1500 },
  server: { proxy: { '/api': 'http://127.0.0.1:8765', '/ws': { target: 'ws://127.0.0.1:8765', ws: true } } },
  test: { environment: 'node' },
})
