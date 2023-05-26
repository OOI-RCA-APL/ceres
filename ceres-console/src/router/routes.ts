import { Address } from '@/address'
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
        path: '/components',
        component: () => import('@/pages/Components.vue'),
        children: [
          {
            path: ':address',
            component: () => import('@/pages/Component.vue'),
            props: (route) => ({
              address: parseAddressOrNull(route.params.address),
            }),
          },
        ],
      },
      {
        path: '/tools/schema-form-playground',
        component: () => import('@/pages/tools/SchemaFormPlayground.vue'),
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

function parseAddressOrNull(value: string | string[]) {
  const string = parseStringOrNull(value)
  if (string == null) {
    return null
  }

  try {
    return new Address(string)
  } catch {
    return null
  }
}

export default routes
