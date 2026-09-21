import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

/**
 * Vitest configuration.
 *
 * - `jsdom` gives component tests a browser-like DOM.
 * - `test.css: false` skips CSS processing (we don't assert styles).
 * - globals: true so `describe/it/expect` need no imports in test files.
 */
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    css: false,
    setupFiles: './src/test/setup.js',
  },
})
