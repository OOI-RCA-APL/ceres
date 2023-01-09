import { RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  {
    path: '',
    component: () => import('@/AppLayout.vue'),
    children: [
      {
        path: '',
        component: () => import('@/pages/Dashboard.vue'),
      },
      {
        path: '/units',
        component: () => import('@/pages/Units.vue'),
        children: [
          {
            path: ':name?',
            component: () => import('@/pages/Unit.vue'),
            props: (route) => ({
              name: parseStringOrNull(route.params.name),
            }),
          },
        ],
      },
      {
        path: '/:catchAll(.*)*',
        redirect: '/units',
      },
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
