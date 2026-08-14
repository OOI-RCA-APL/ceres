import { defineNuxtConfig } from 'nuxt/config'

export default defineNuxtConfig({
  compatibilityDate: '2026-08-14',
  // The console is a static bundle the engine serves, with no server side of its own.
  ssr: false,
  // Nuxt UI registers the Tailwind Vite plugin itself, adding it here breaks the build.
  modules: ['@vue-macros/nuxt', '@nuxt/eslint', '@pinia/nuxt', '@nuxt/ui'],
  vue: {
    // Allow safe destructured assignment of component props.
    propsDestructure: true,
  },
  css: ['@/assets/css/main.css'],
  colorMode: {
    preference: 'dark',
    fallback: 'dark',
  },
  // Don't prefix global component names with their path.
  components: [
    {
      path: '@/components',
      pathPrefix: false,
    },
  ],
  devServer: {
    port: 8086,
  },
  nitro: {
    devProxy: {
      '/api': {
        target: 'http://localhost:8080/api',
        changeOrigin: true,
        ws: true,
      },
    },
  },
})
