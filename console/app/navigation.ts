import { defineStore } from 'pinia'
import { computed, reactive } from 'vue'
import {
  type RouteLocationNormalizedLoaded,
  type RouteLocationRaw,
  useRoute,
  useRouter,
} from 'vue-router'

import { useNotify } from '@/notify'

declare module 'vue-router' {
  interface RouteMeta {
    /** `true` requires a signed-in user, `'admin'` requires an administrator. */
    auth?: boolean | 'admin'
  }
}

declare module '#app' {
  interface PageMeta {
    auth?: boolean | 'admin'
  }
}

/** Whether `user` may visit `route`, per the route's `auth` metadata. */
export function userCanAccess(
  user: { admin?: boolean } | null,
  route: { matched: { meta: { auth?: boolean | 'admin' } }[] },
): boolean {
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

export function getLoginRedirectPath(redirect: string) {
  return `/login?redirect=${encodeURI(redirect)}`
}

/** The value of a path parameter, read once for the life of the page instance holding it.

A page is mounted per path, and the route changes while the page it is leaving is still on
screen, so a parameter followed from the route rerenders that page's own state against the next
page's subject for a frame. Query parameters are excluded on purpose: they change without
remounting, so a page that answers to one reads it from `useNavigation().route` instead.
*/
export function usePageParameter(name: string): string {
  const value = useRoute().params[name]
  const parameter = Array.isArray(value) ? value[0] : value
  if (parameter == null || parameter === '') {
    throw new Error(`The route has no "${name}" parameter, so no page instance can belong to one.`)
  }

  return parameter
}

export const useNavigation = defineStore('navigation', () => {
  const route = useRoute()
  const router = useRouter()

  const state = reactive({
    reloads: 0,
  })

  const self = {
    key: computed(() => `${route.path}|${state.reloads}`),
    route: computed(() => route),
    router: computed(() => router),

    /** The component address the current route is on, or null anywhere else. */
    component: computed(() => {
      const parameter = route.params.address
      return typeof parameter === 'string' && parameter !== '' ? parameter : null
    }),

    reload() {
      state.reloads++
    },

    refresh() {
      router.go(0)
    },

    async go(to: RouteLocationRaw) {
      const { href } = router.resolve(to)
      const url = new URL(`http://domain${href}`)
      const path = url.pathname

      if (route.path === path) {
        await router.replace(to)
        self.reload()
      } else {
        await router.push(to)
      }
    },

    /** Send `user` to the login page when they cannot reach the page they are on.

    Route middleware only runs on a navigation, so an identity that changes underneath one leaves
    whoever holds it now looking at a page they were never let into.
    */
    async enforceAccess(user: { admin?: boolean } | null) {
      if (userCanAccess(user, route)) {
        return
      }

      useNotify().warn('You do not have access to that resource.')
      await router.replace(getLoginRedirectPath(route.fullPath))
    },

    async push(to: RouteLocationRaw) {
      await router.push(to)
    },

    async replace(to: RouteLocationRaw) {
      await router.replace(to)
    },

    resolve(to: RouteLocationRaw, currentLocation?: RouteLocationNormalizedLoaded) {
      return router.resolve(to, currentLocation)
    },

    back() {
      router.back()
    },

    forward() {
      router.forward()
    },
  }

  return self
})

export type Navigation = ReturnType<typeof useNavigation>
