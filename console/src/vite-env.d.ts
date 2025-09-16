/* eslint-disable */
/// <reference types="vite/client" />
/// <reference types="vue-macros/macros-global" />

import { Quasar } from 'quasar'
import 'vue'

declare module '@vue/runtime-core' {
  interface ComponentCustomProperties {
    $q: Quasar
  }
}

declare namespace NodeJS {
  interface ProcessEnv {
    NODE_ENV: string
    VUE_ROUTER_MODE: 'hash' | 'history' | 'abstract' | undefined
    VUE_ROUTER_BASE: string | undefined
  }
}
