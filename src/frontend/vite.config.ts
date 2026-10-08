import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: { '/api': { target: process.env.API_PROXY_TARGET ?? 'http://api:8000', changeOrigin: true }, '/health': { target: process.env.API_PROXY_TARGET ?? 'http://api:8000' } },
  },
  // Whole-app jsdom tests load lazy routes; parallel runs can double their time.
  test: { environment: 'jsdom', globals: true, testTimeout: 15_000, setupFiles: ['./src/test/setup.ts'], exclude: ['e2e/**', 'node_modules/**'] },
})
