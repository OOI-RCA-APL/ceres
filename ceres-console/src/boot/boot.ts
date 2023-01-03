import 'echarts'
import { createPinia } from 'pinia'
import { boot } from 'quasar/wrappers'
import Chart from 'vue-echarts'
import { VueQueryPlugin } from 'vue-query'

export default boot(({ app }) => {
  app.use(VueQueryPlugin)
  app.use(createPinia())
  app.component('Chart', Chart)
})
