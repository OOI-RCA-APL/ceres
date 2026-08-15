import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import { defineNuxtConfig } from 'nuxt/config'

/**
 * Read the project version, which is the one the engine shipping this console reports.
 *
 * Throws when the version is missing, a build that guessed one being worse than no build.
 */
function projectVersion(): string {
  const path = fileURLToPath(new URL('../pyproject.toml', import.meta.url))
  const project = /^\[project\]$(.*?)(?=^\[)/ms.exec(readFileSync(path, 'utf8'))
  const version = project && /^version = "([^"]+)"$/m.exec(project[1]!)
  if (version == null) {
    throw new Error(`No [project] version found in ${path}.`)
  }

  return version[1]!
}

export default defineNuxtConfig({
  compatibilityDate: '2026-08-14',
  // The release this console ships in. Nuxt compares it to tell a running console that a
  // newer one is being served, and the default is a fresh UUID that would make the
  // committed bundle differ on every build.
  buildId: projectVersion(),
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
    // Taken from the environment so the CLI can put this console on the address the built-in
    // one would have had, standing in for it rather than sitting beside it.
    host: process.env.NUXT_HOST,
    port: Number(process.env.NUXT_PORT ?? 8086),
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
  // HTTP only. Websockets connect straight to the engine port in development, the dev
  // proxy cannot upgrade them and a failed upgrade restarts the dev server.
  nitro: {
    // The build output stays inside this directory and `postbuild` copies it into the
    // package. Pointing `output.publicDir` at the package instead empties that directory
    // every time the dev server starts, taking the committed bundle with it.
    devProxy: {
      '/api': {
        // The engine moves aside when the CLI serves this console in place of the built-in one,
        // so where it ended up is passed in rather than assumed.
        target: `http://localhost:${process.env.CERES_API_PORT ?? 8080}/api`,
        changeOrigin: true,
      },
    },
  },
})
