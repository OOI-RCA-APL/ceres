import { VueQueryPlugin } from '@tanstack/vue-query'
import { createPinia } from 'pinia'
import { boot } from 'quasar/wrappers'
import 'echarts'
import 'prismjs/components/prism-json'
import 'prismjs/components/prism-log'
import 'prismjs/components/prism-yaml'

import { renderVirtualScrollWhileScrolling } from '@/virtual-scroll'

export default boot(({ app }) => {
  // Before anything is rendered, since it takes effect as each virtual scroller starts listening.
  renderVirtualScrollWhileScrolling()

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
