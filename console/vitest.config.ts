import path from 'path'

import Vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vitest/config'
import VueMacros from 'vue-macros/vite'

// Quasar owns the app's own Vite configuration, so the pieces the sources actually depend on are
// named again here rather than reached for through it. Vue Macros is one of them, since the stores
// and composables are written with the reactivity transform and do not parse without it.
export default defineConfig({
  plugins: [VueMacros({ plugins: { vue: Vue() } }) as never],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  test: {
    include: ['src/**/*.test.ts'],
    environment: 'happy-dom',
  },
})
