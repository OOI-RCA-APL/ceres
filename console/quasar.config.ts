// https://v2.quasar.dev/quasar-cli-vite/quasar-config-js
/* eslint-env node */

import fs from 'fs'
import path from 'path'

import dotenv from 'dotenv'
import VueMacros from 'unplugin-vue-macros/vite'

import { defineConfig } from '#q-app/wrappers'

export default defineConfig((context) => {
  function getDevelopmentEnvironment() {
    if (context.prod) {
      return null
    }

    const values =
      dotenv.config({
        path: path.join(__dirname, '.env'),
        override: true,
      }).parsed ?? {}

    return {
      ceresApiPort: Number(values.DEVELOPMENT_CERES_API_PORT ?? 8080),
      ceresConsolePort: Number(values.DEVELOPMENT_CERES_CONSOLE_PORT ?? 8085),
    }
  }

  const development = getDevelopmentEnvironment()

  return {
    eslint: {
      warnings: true,
      errors: true,
    },

    // https://v2.quasar.dev/quasar-cli-vite/boot-files
    boot: ['boot'],

    // https://v2.quasar.dev/quasar-cli-vite/quasar-config-js#css
    css: ['app.scss'],

    // https://github.com/quasarframework/quasar/tree/dev/extras
    extras: ['mdi-v7', 'material-icons', 'roboto-font'],

    // https://v2.quasar.dev/quasar-cli-vite/quasar-config-js#build
    build: {
      distDir: path.join(__dirname, '../ceres/static/console'),
      env: development
        ? {
            DEVELOPMENT_CERES_API_PORT: String(development.ceresApiPort),
            DEVELOPMENT_CERES_CONSOLE_PORT: String(development.ceresConsolePort),
          }
        : undefined,
      vueRouterMode: 'history',
      vitePlugins: [VueMacros() as any, AllowDotURLsPlugin()],
      extendViteConf() {
        return {
          resolve: {
            alias: {
              '@': path.resolve(__dirname, './src'),
            },
          },
          build: {
            minify: 'terser',
            rollupOptions: {
              output: {
                inlineDynamicImports: true,
              },
            },
          },
        }
      },
    },

    // https://v2.quasar.dev/quasar-cli-vite/quasar-config-js#devServer
    devServer: development
      ? {
          open: true,
          port: development.ceresConsolePort,
          proxy: {
            '/api': {
              target: `http://0.0.0.0:${development.ceresApiPort}`,
              changeOrigin: true,
              ws: true,
              secure: false,
            },
          },
        }
      : {},

    // https://v2.quasar.dev/quasar-cli-vite/quasar-config-js#framework
    framework: {
      config: {},
      plugins: ['Dark', 'Dialog', 'LocalStorage', 'Meta', 'Notify'],
      cssAddon: true,
    },

    // https://v2.quasar.dev/options/animations
    animations: 'all',
  }
})

function AllowDotURLsPlugin() {
  return {
    name: 'allow-dot-urls-plugin',
    configureServer: (server: any) => {
      server.middlewares.use((request: any, _: any, next: any) => {
        const path = request.url.split('?', 2)[0]
        if (
          !request.url.startsWith('/@') && // Ignore virtual files provided by vite plugins.
          !request.url.startsWith('/api/') && // Ignore API proxy configured below.
          !fs.existsSync(`./public${path}`) && // Ignore files served directly from public folder.
          !fs.existsSync(`.${path}`) // Ignore actual files.
        ) {
          request.url = '/' // Rewrite all other requests to root.
        }
        next()
      })
    },
  }
}
