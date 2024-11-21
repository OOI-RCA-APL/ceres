/* eslint-disable @typescript-eslint/no-var-requires */
/* eslint-env node */

// https://v2.quasar.dev/quasar-cli-vite/quasar-config-js

const fs = require('fs')
const path = require('path')

const { merge } = require('lodash')
const { configure } = require('quasar/wrappers')
const VueMacros = require('unplugin-vue-macros/vite')

module.exports = configure((context) => {
  function getDevelopmentEnvironment() {
    if (context.prod) {
      return null
    }

    const dotenv =
      require('dotenv').config({
        path: path.join(__dirname, '.env'),
        override: true,
      }).parsed ?? {}

    return {
      ceresApiPort: Number(dotenv.DEVELOPMENT_CERES_API_PORT ?? 8080),
      ceresConsolePort: Number(dotenv.DEVELOPMENT_CERES_CONSOLE_PORT ?? 8085),
    }
  }

  development = getDevelopmentEnvironment()

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
      target: {
        browser: ['es2019', 'edge88', 'firefox78', 'chrome87', 'safari13.1'],
        node: 'node16',
      },
      env: development
        ? {
            DEVELOPMENT_CERES_API_PORT: development.ceresApiPort,
            DEVELOPMENT_CERES_CONSOLE_PORT: development.ceresConsolePort,
          }
        : undefined,
      vueRouterMode: 'history',
      vitePlugins: [AllowDotURLsPlugin()],
      extendViteConf(config) {
        // Allow '@' to be used as an alias for the 'src' directory.
        config.resolve ??= {}
        config.resolve.alias ??= {}
        config.resolve.alias['@'] = path.resolve(__dirname, './src')

        // Insert the Vue Macros plugin directly after the 'vite:vue' plugin.
        const vuePluginIndex = config.plugins.findIndex((plugin) => plugin.name === 'vite:vue')
        config.plugins.splice(vuePluginIndex + 1, 0, VueMacros())
        config.build = merge({}, config.build, {
          minify: 'terser',
          rollupOptions: {
            output: {
              inlineDynamicImports: true,
            },
          },
        })

        return config
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
    configureServer: (server) => {
      server.middlewares.use((request, _, next) => {
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
