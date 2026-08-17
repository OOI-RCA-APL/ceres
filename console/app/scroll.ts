import { useEventListener } from '@vueuse/core'
import { debounce } from 'lodash-es'
import { type MaybeRefOrGetter, toValue, watch } from 'vue'

import { usePersisted } from '@/persistence'

// Enough to cover every workspace anyone keeps open, without letting a long-lived browser profile
// accumulate a position for everything ever visited. The oldest are dropped first.
const positionLimit = 100

// How long to keep trying to restore. A workspace loads its data and lays out its widgets after
// the switch, and widgets that stream their rows keep growing for a while after that so the page
// is too short to scroll all the way back for some time. Giving up eventually is what stops the
// page jumping once the user has started reading somewhere else.
const restoreTimeout = 3000

/** Remember the window's scroll position for each key, and restore it when a key comes back.

`key` names whatever is being switched between, and a null key is nothing to remember. The
position is recorded as the key leaves and restored once the new content is tall enough to hold
it, which is not the same frame the key changes on.

`settled` says whether moving the page right now would be welcome. Switching between keys while
the page is somewhere the user is still reading moves the ground under them so a caller that has
such a place says so and the position is neither taken nor put back until they are past it.

Positions are only put back on a switch. Arriving is a different act from switching, and a page
that has just been navigated to starts at the top with whatever it leads with in view rather than
several hundred pixels below it with no sign that anything was skipped.

Positions are kept per device since where you were a moment ago belongs to this browser rather
than to the account.
*/
export function useScrollMemory(
  key: MaybeRefOrGetter<string | null>,
  settled?: MaybeRefOrGetter<boolean>,
  floor?: MaybeRefOrGetter<number>,
) {
  const state = usePersisted({
    schema: ({ object, record, string, number }) =>
      object({ positions: record(string(), number()).default({}) }),
    methods: [{ type: 'local-storage', key: ['workspace-scroll'] }],
  })

  let restoring: string | null = null

  function remember(target: string, position: number) {
    // Rewriting the entry moves it to the end so the eviction below drops the least recently
    // used.
    const kept = Object.entries(state.positions).filter(([current]) => current !== target)
    const entries = [...kept, [target, position] as const]

    state.positions = Object.fromEntries(entries.slice(-positionLimit))
  }

  function restore(target: string) {
    // Never above the floor so whatever the caller has pinned to the top of the window stays
    // pinned rather than dropping back down the page as the switch lands.
    const position = Math.max(state.positions[target] ?? 0, toValue(floor) ?? 0)
    const deadline = performance.now() + restoreTimeout
    restoring = target

    function attempt() {
      // Another switch has started, and it owns the scroll position now.
      if (restoring !== target) {
        return
      }

      // Scroll as far as the page currently reaches on every attempt rather than waiting for it
      // to grow all the way. A page that never gets tall enough then still lands as close as it
      // can, instead of sitting at the top having silently given up.
      const reachable = Math.max(0, document.documentElement.scrollHeight - window.innerHeight)
      window.scrollTo({ top: Math.min(position, reachable) })

      if (reachable >= position) {
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

  // A page that cannot scroll has no position worth keeping. Recording a zero from one would wipe
  // where the user actually was, which is exactly the state a page is in while its content is
  // still arriving or has just been torn down.
  function isMeasurable(): boolean {
    return document.documentElement.scrollHeight - window.innerHeight > 0
  }

  function isSettled(): boolean {
    return toValue(settled) ?? true
  }

  watch(
    () => toValue(key),
    (next, previous) => {
      // Arriving is not a switch, whether the key was unset or merely absent. A page decides what
      // to show after it mounts so the first real key arrives as a change from nothing, and
      // treating that as a switch would put back a position the user never left.
      if (previous == null) {
        return
      }

      if (!isSettled()) {
        return
      }

      if (isMeasurable()) {
        remember(previous, window.scrollY)
      }

      if (next == null) {
        restoring = null
        return
      }

      restore(next)
    },
    // Run for the first key as well so that arriving is seen and taken as the starting point the
    // switches after it are measured against.
    { immediate: true },
  )

  // Recorded as the page is scrolled rather than only when a tab is left because a reload or a
  // closed browser never gets to leave. Writes are debounced, and skipped while a restore is
  // still working, which would otherwise record the top of a page that has not grown yet.
  const record = debounce(() => {
    const current = toValue(key)
    if (current != null && restoring == null && isMeasurable() && isSettled()) {
      remember(current, window.scrollY)
    }
  }, 200)

  useEventListener(window, 'scroll', record, { passive: true })
}
