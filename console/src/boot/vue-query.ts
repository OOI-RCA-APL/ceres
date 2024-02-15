import { VueQueryPlugin } from '@tanstack/vue-query'
import { boot } from 'quasar/wrappers'

export default boot(({ app }) => {
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
