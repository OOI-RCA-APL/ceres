import { RouteRecordRaw } from 'vue-router'

import AppLayout from '@/AppLayout.vue'
import Account from '@/pages/Account.vue'
import CreateUser from '@/pages/CreateUser.vue'
import Dashboard from '@/pages/Dashboard.vue'
import Login from '@/pages/Login.vue'
import User from '@/pages/User.vue'
import Users from '@/pages/Users.vue'
import Workspace from '@/pages/Workspace.vue'
import SchemaFormPlayground from '@/pages/developer/SchemaFormPlayground.vue'

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
        path: '/login',
        component: Login,
      },
      {
        path: '/account',
        meta: {
          auth: 'viewer',
        },
        component: Account,
      },
      {
        path: '/users/create',
        meta: {
          auth: 'admin',
        },
        component: CreateUser,
      },
      {
        path: '/users/:id',
        meta: {
          auth: 'admin',
        },
        component: User,
        props: (route) => ({
          id: parseStringOrNull(route.params.id),
        }),
      },
      {
        path: '/users',
        meta: {
          auth: 'admin',
        },
        component: Users,
      },
      {
        path: '/workspaces/:name',
        meta: {
          auth: 'viewer',
        },
        props: (route) => ({
          name: parseStringOrNull(route.params.name),
        }),
        component: Workspace,
      },
      {
        path: '/developer/schema-form-playground',
        component: SchemaFormPlayground,
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
