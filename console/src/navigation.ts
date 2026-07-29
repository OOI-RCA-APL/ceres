import { defineStore } from 'pinia'
import { computed, reactive } from 'vue'
import { RouteLocationNormalizedLoaded, RouteLocationRaw, useRoute, useRouter } from 'vue-router'

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
