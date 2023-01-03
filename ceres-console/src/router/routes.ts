import AppLayout from '@/AppLayout.vue'
import Component from '@/pages/Component.vue'
import Dashboard from '@/pages/Dashboard.vue'
import Unit from '@/pages/Unit.vue'
import Units from '@/pages/Units.vue'
import { RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  {
    path: '',
    component: AppLayout,
    children: [
      {
        path: '',
        component: Dashboard,
      },
      {
        path: '/units',
        component: Units,
        children: [
          {
            path: ':unitName/components/:componentName',
            component: Component,
            props: (route) => ({
              unitName: route.params.unitName,
              componentName: route.params.componentName,
            }),
          },
          {
            path: ':name?',
            component: Unit,
            props: (route) => ({
              name: parseStringOrNull(route.params.name),
            }),
          },
        ],
      },
      // {
      //   path: '/:catchAll(.*)*',
      //   redirect: '/units',
      // },
    ],
  },
]

function parseStringOrNull(value: string | string[]) {
  if (typeof value === 'string') {
    value = value.trim()
    if (value !== '') {
      return value
    }
  }

  return value[0] ?? null
}

export default routes
