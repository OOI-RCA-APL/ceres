import { RouteRecordRaw } from 'vue-router'

import AppLayout from '@/AppLayout.vue'
import Account from '@/pages/Account.vue'
import CreateUser from '@/pages/CreateUser.vue'
import Home from '@/pages/Home.vue'
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
        component: Home,
      },
      {
        path: '/login',
        component: Login,
      },
      {
        path: '/account',
        meta: {
          auth: true,
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
        path: '/workspaces/:id',
        meta: {
          auth: true,
        },
        props: (route) => ({
          id: parseStringOrNull(route.params.id),
        }),
        component: Workspace,
      },
      {
        path: '/components/:address(.*)',
        component: () => import('@/pages/ComponentDetail.vue'),
        meta: { auth: true },
      },
      {
        path: '/groups/create',
        component: () => import('@/pages/CreateGroup.vue'),
        meta: { auth: 'admin' },
      },
      {
        path: '/groups',
        component: () => import('@/pages/Groups.vue'),
        meta: { auth: 'admin' },
      },
      {
        path: '/groups/:id',
        component: () => import('@/pages/GroupDetail.vue'),
        meta: { auth: 'admin' },
      },
      {
        path: '/developer/schema-form-playground',
        component: SchemaFormPlayground,
      },
      {
        path: '/:catchAll(.*)*',
        redirect: '/',
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
