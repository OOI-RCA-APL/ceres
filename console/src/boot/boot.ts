import { VueQueryPlugin } from '@tanstack/vue-query'
import { createPinia } from 'pinia'
import { boot } from 'quasar/wrappers'
import 'echarts'
import 'prismjs/components/prism-json'
import 'prismjs/components/prism-log'
import 'prismjs/components/prism-yaml'

export default boot(({ app }) => {
  app.use(createPinia())
  app.use(VueQueryPlugin, {
    queryClientConfig: {
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    },
  })
})
