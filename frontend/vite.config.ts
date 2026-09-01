import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  server: {
    proxy: {
      // ORDER IS LOAD-BEARING. Vite matches these keys in declaration order,
      // and '/api' is a prefix of '/api/auth'. Declared the other way round,
      // every Better Auth request - including the Google callback - would be
      // proxied to the FastAPI service, which knows nothing about /api/auth and
      // would answer 404. The symptom is a login that redirects to Google,
      // comes back, and lands on a blank 404 with no error anywhere in the
      // Node server's log, because the request never reached it.
      '/api/auth': 'http://127.0.0.1:3000',
      '/api': 'http://127.0.0.1:8000',
      '/ws': {
        target: 'ws://127.0.0.1:8000',
        ws: true,
      },
    },
  },
})
