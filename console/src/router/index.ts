import { route } from 'quasar/wrappers'
import {
  RouteLocation,
  createMemoryHistory,
  createRouter,
  createWebHashHistory,
  createWebHistory,
} from 'vue-router'

import { UserRole } from '@/api/models'
import routes from '@/router/routes'

export function userCanAccess(user: { role: UserRole } | null, route: RouteLocation): boolean {
  const requiresAdmin = route.matched.some((record) => record.meta.auth === 'admin')
  const requiresOperator = route.matched.some((record) => record.meta.auth === 'operator')
  const requiresViewer = route.matched.some((record) => record.meta.auth === 'viewer')

  let allowed: UserRole[]
  if (requiresAdmin) {
    allowed = ['admin']
  } else if (requiresOperator) {
    allowed = ['admin', 'operator']
  } else if (requiresViewer) {
    allowed = ['admin', 'operator', 'viewer']
  } else {
    return true
  }

  if (user == null) {
    return false
  }

  return allowed.includes(user.role)
}

export default route(() => {
  const createHistory = process.env.SERVER
    ? createMemoryHistory
    : process.env.VUE_ROUTER_MODE === 'history'
    ? createWebHistory
    : createWebHashHistory

  const Router = createRouter({
    scrollBehavior: () => ({ left: 0, top: 0 }),
    routes,

    history: createHistory(process.env.VUE_ROUTER_BASE),
  })

  return Router
})
