import { defineNuxtConfig } from 'nuxt/config'

export default defineNuxtConfig({
  compatibilityDate: '2026-08-14',
  // The console is a static bundle the engine serves, with no server side of its own.
  ssr: false,
  // Nuxt UI registers the Tailwind Vite plugin itself, adding it here breaks the build.
  modules: ['@vue-macros/nuxt', '@nuxt/eslint', '@pinia/nuxt', '@nuxt/ui'],
  ui: {
    // Nuxt UI components register as C* (c-button, c-modal), the console's own prefix.
    prefix: 'C',
  },
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
  hooks: {
    // The developer section is a dev-only surface for iterating on the theme and
    // components in isolation, production builds ship without it.
    'pages:extend'(pages) {
      if (process.env.NODE_ENV === 'production') {
        const withoutDeveloperPages = pages.filter(
          (page) => !(page.path ?? '').startsWith('/developer'),
        )
        pages.splice(0, pages.length, ...withoutDeveloperPages)
      }
    },
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
