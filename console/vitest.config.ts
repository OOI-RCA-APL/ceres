import { fileURLToPath } from 'node:url'

import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vitest/config'
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
  },
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./app', import.meta.url)),
    },
  },
})
