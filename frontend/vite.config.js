import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dev proxy: the SPA calls same-origin /api and /static paths, which are
// forwarded to FastAPI. Keeping everything same-origin means the session
// cookie stays first-party and no CORS friction in development.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/static': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
