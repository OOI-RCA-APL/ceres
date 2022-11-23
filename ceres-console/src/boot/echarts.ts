import 'echarts'
import { boot } from 'quasar/wrappers'
import Chart from 'vue-echarts'

export default boot(({ app }) => {
  app.component('Chart', Chart)
})
