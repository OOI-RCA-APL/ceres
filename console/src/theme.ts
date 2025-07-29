import { computed } from 'vue'

import { usePreferences } from '@/preferences'

export function useTheme() {
  const preferences = usePreferences()

  function darklight<D, L>(dark: (() => D) | D, light: (() => L) | L) {
    const value = preferences.isDarkModeEnabled ? dark : light
    if (typeof value === 'function') {
      return (value as any)()
    }

    return value
  }

  return {
    darklight,
    // darklight: getter(
    //   computed(() => preferences.isDarkModeEnabled),
    //   () => darklight
    // ),
    dark: computed(() => preferences.isDarkModeEnabled),
    light: computed(() => !preferences.isDarkModeEnabled),
  }
}
