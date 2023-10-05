import { defineStore } from 'pinia'
import { debounce } from 'quasar'
import { computed, reactive, watchEffect } from 'vue'

export const useResize = defineStore('resize', () => {
  const state = reactive({
    key: 0,
  })

  watchEffect((onCleanup) => {
    const onResize = debounce(() => {
      if (state.key >= Number.MAX_SAFE_INTEGER - 1) {
        state.key = 0
      } else {
        state.key += 1
      }
    }, 250)

    window.addEventListener('resize', onResize)
    onCleanup(() => {
      window.removeEventListener('resize', onResize)
    })
  })

  return {
    key: computed(() => state.key),
  }
})
