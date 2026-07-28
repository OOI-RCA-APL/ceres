import { watch, MaybeRefOrGetter, toValue } from 'vue'

import { usePersisted } from '@/persistence'

// Enough to cover every workspace anyone keeps open, without letting a long-lived browser profile
// accumulate a position for everything ever visited. The oldest are dropped first.
const positionLimit = 100

// How long to keep trying to restore. A workspace loads its data and lays out its widgets after
// the switch, so the page is briefly too short to scroll to where it was. Giving up quietly is
// better than jumping the page once the user has started reading somewhere else.
const restoreTimeout = 1000

/** Remember the window's scroll position for each key, and restore it when a key comes back.

`key` names whatever is being switched between, and a null key is nothing to remember. The
position is recorded as the key leaves and restored once the new content is tall enough to hold
it, which is not the same frame the key changes on.

Positions are kept per device, since where you were a moment ago belongs to this browser rather
than to the account.
*/
export function useScrollMemory(key: MaybeRefOrGetter<string | null>) {
  const state = usePersisted({
    schema: ({ object, record, string, number }) =>
      object({ positions: record(string(), number()).default({}) }),
    methods: [{ type: 'local-storage', key: ['workspace-scroll'] }],
  })

  let restoring: string | null = null

  function remember(target: string, position: number) {
    // Rewriting the entry moves it to the end, which is what makes the eviction below drop
    // whatever has gone longest without being looked at.
    const kept = Object.entries(state.positions).filter(([current]) => current !== target)
    const entries = [...kept, [target, position] as const]

    state.positions = Object.fromEntries(entries.slice(-positionLimit))
  }

  function restore(target: string) {
    const position = state.positions[target] ?? 0
    const deadline = performance.now() + restoreTimeout
    restoring = target

    function attempt() {
      // Another switch has started, and it owns the scroll position now.
      if (restoring !== target) {
        return
      }

      const reachable = document.documentElement.scrollHeight - window.innerHeight
      if (reachable >= position) {
        window.scrollTo({ top: position })
        restoring = null
        return
      }

      if (performance.now() < deadline) {
        requestAnimationFrame(attempt)
      } else {
        restoring = null
      }
    }

    requestAnimationFrame(attempt)
  }

  watch(
    () => toValue(key),
    (next, previous) => {
      if (previous != null) {
        remember(previous, window.scrollY)
      }

      if (next == null) {
        restoring = null
        return
      }

      restore(next)
    }
  )
}
