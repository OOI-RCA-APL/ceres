/* eslint-disable @typescript-eslint/no-var-requires */
/* eslint-env node */

// https://v2.quasar.dev/quasar-cli-vite/quasar-config-js

const { configure } = require('quasar/wrappers')
const path = require('path')

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
      ceresApiPort: Number(dotenv.DEVELOPMENT_CERES_API_PORT ?? 9000),
      ceresConsolePort: Number(dotenv.DEVELOPMENT_CERES_CONSOLE_PORT ?? 10000),
    }
  }

  development = getDevelopmentEnvironment()

  return {
    eslint: {
      warnings: true,
      errors: true,
    },

    // https://v2.quasar.dev/quasar-cli-vite/boot-files
    boot: ['echarts'],

    // https://v2.quasar.dev/quasar-cli-vite/quasar-config-js#css
    css: ['app.scss'],

    // https://github.com/quasarframework/quasar/tree/dev/extras
    extras: ['roboto-font', 'material-icons'],

    // https://v2.quasar.dev/quasar-cli-vite/quasar-config-js#build
    build: {
      distDir: path.join(__dirname, '../ceres/ceres/static/console'),
      target: {
        browser: ['es2019', 'edge88', 'firefox78', 'chrome87', 'safari13.1'],
        node: 'node16',
      },
      vueRouterMode: 'history',
      viteVuePluginOptions: {
        reactivityTransform: true,
      },
      extendViteConf(config) {
        config.resolve ??= {}
        config.resolve.alias ??= {}
        config.resolve.alias['@'] = path.resolve(__dirname, './src')
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
              target: `http://0.0.0.0:${development.ceresApiPort}/api`,
              changeOrigin: true,
            },
          },
        }
      : {},

    // https://v2.quasar.dev/quasar-cli-vite/quasar-config-js#framework
    framework: {
      config: {},
      plugins: ['Dark', 'Dialog', 'LocalStorage', 'Meta', 'Notify'],
    },

    // https://v2.quasar.dev/options/animations
    animations: [],
  }
})
