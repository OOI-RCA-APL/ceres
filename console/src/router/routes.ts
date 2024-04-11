import { Address } from '@/api/address'
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
        path: '/account',
        meta: {
          auth: 'viewer',
        },
        component: () => import('@/pages/Account.vue'),
      },
      {
        path: '/users/create',
        meta: {
          auth: 'admin',
        },
        component: () => import('@/pages/CreateUser.vue'),
      },
      {
        path: '/users/:id',
        meta: {
          auth: 'admin',
        },
        component: () => import('@/pages/User.vue'),
        props: (route) => ({
          id: parseStringOrNull(route.params.id),
        }),
      },
      {
        path: '/users',
        meta: {
          auth: 'admin',
        },
        component: () => import('@/pages/Users.vue'),
      },
      {
        path: '/systems/@',
        redirect: '/systems',
      },
      {
        path: '/systems/:address?',
        component: () => import('@/pages/System.vue'),
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
