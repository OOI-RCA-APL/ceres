import { Quasar } from 'quasar'
import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'

// Import icon libraries
import '@quasar/extras/fontawesome-v6/fontawesome-v6.css'
import '@quasar/extras/material-icons/material-icons.css'

// Import fonts.
import '@quasar/extras/roboto-font/roboto-font.css'

// Import animations from Animate.css.
import '@quasar/extras/animate/fadeIn.css'

// Import Quasar SASS.
import 'quasar/src/css/index.sass'

// Import custom CSS.
import './style.css'

import App from './App.vue'
import routes from './routes'

const app = createApp(App)

const router = createRouter({
  history: createWebHistory(),
  routes,
})

app.use(router)

app.use(Quasar, {
  plugins: {}, // import Quasar plugins and add here
})

// Assumes you have a <div id="app"></div> in your index.html
app.mount('#app')
