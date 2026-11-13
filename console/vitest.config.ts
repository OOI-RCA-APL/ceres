import { fileURLToPath } from 'node:url'

import vue from '@vitejs/plugin-vue'
import { configDefaults, defineConfig } from 'vitest/config'
import VueMacros from 'vue-macros/vite'

export default defineConfig({
  // The reactivity transform runs in tests too, so modules using $ref and $computed test as
  // they ship.
  plugins: [
    VueMacros({
      plugins: {
        vue: vue(),
      },
    }),
  ],
  test: {
    environment: 'happy-dom',
    // Playwright runs `e2e` against a live engine.
    exclude: [...configDefaults.exclude, 'e2e/**'],
    setupFiles: ['tests/setup.ts'],
  },
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./app', import.meta.url)),
    },
  },
})
