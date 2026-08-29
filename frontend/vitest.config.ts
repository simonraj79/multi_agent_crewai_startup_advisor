import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vitest/config'

// Kept separate from vite.config.ts so the dev-server proxy config never has to
// be loaded by the runner. `npm test` maps to `vitest run`: single pass, exits.
export default defineConfig({
  plugins: [vue()],
  test: {
    environment: 'jsdom',
    include: ['tests/**/*.spec.ts'],
    restoreMocks: true,
    clearMocks: true,
  },
})
