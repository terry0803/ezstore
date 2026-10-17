import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
  ],
  server: {
    port: 5173,
    proxy: {
      '/agent-api': {
        // Local ADK playground: agents-cli playground --port 8501.
        target: 'http://127.0.0.1:8501',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/agent-api(?=\/|$)/, ''),
        proxyTimeout: 300_000,
      },
      '/api': {
        target: 'http://localhost:8080',
        changeOrigin: true,
      },
      '/swagger': {
        target: 'http://localhost:8080',
        changeOrigin: true,
      },
    },
  },
})
