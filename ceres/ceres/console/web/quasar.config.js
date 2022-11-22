/* eslint-disable @typescript-eslint/no-var-requires */
/* eslint-env node */

// https://v2.quasar.dev/quasar-cli-vite/quasar-config-js

const { configure } = require('quasar/wrappers')
const path = require('path')

module.exports = configure(() => {
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
      distDir: path.join(__dirname, '../static'),
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
        // config.rollupOptions = {
        //   output: {
        //     manualChunks: false,
        //     inlineDynamicImports: true,
        //     entryFileNames: '[name].js', // currently does not work for the legacy bundle
        //     assetFileNames: '[name].[ext]', // currently does not work for images
        //   },
        // }
        config.rollupOptions = {
          output: {
            manualChunks: {},
          },
        }

        return config
      },
    },

    // https://v2.quasar.dev/quasar-cli-vite/quasar-config-js#devServer
    devServer: {
      open: true,
    },

    // https://v2.quasar.dev/quasar-cli-vite/quasar-config-js#framework
    framework: {
      config: {},
      plugins: ['Dark', 'Dialog', 'LocalStorage', 'Meta', 'Notify'],
    },

    // https://v2.quasar.dev/options/animations
    animations: [],
  }
})
