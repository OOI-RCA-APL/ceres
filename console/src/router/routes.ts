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
        path: '/login',
        component: () => import('@/pages/Login.vue'),
      },
      {
        path: '/components/@',
        redirect: '/components',
      },
      {
        path: '/components/:address?',
        component: () => import('@/pages/Component.vue'),
        props: (route) => ({
          address: parseAddressOrNull(route.params.address) ?? new Address('@'),
        }),
      },
      {
        path: '/developer/schema-form-playground',
        component: () => import('@/pages/developer/SchemaFormPlayground.vue'),
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
