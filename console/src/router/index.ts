import { route } from 'quasar/wrappers'
import {
  RouteLocation,
  createMemoryHistory,
  createRouter,
  createWebHashHistory,
  createWebHistory,
} from 'vue-router'

import routes from '@/router/routes'

export function userCanAccess(user: { admin?: boolean } | null, route: RouteLocation): boolean {
  const requiresAdmin = route.matched.some((record) => record.meta.auth === 'admin')
  const requiresAuthenticated = route.matched.some((record) => record.meta.auth === true)

  if (requiresAdmin) {
    return user?.admin === true
  }

  if (requiresAuthenticated) {
    return user != null
  }

  return true
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
