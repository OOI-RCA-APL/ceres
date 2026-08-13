import { useEventListener, useResizeObserver } from '@vueuse/core'
import { defineStore } from 'pinia'
import { computed, MaybeRefOrGetter, nextTick, ref, toValue, watch } from 'vue'
import { LocationQuery } from 'vue-router'
import Zod from 'zod'

import { useSettings } from '@/api/settings'
import { usePersisted } from '@/persistence'

/** Ease a step down into workspace content that is just appearing.

The content mounts and loads asynchronously, so the scroll waits until the page has grown the
room to take it, and gives up quietly when nothing appears.
*/
export async function stepIntoWorkspaces(step = 200, timeout = 3000) {
  const deadline = performance.now() + timeout
  while (
    document.body.scrollHeight <= window.scrollY + window.innerHeight + step / 2 &&
    performance.now() < deadline
  ) {
    await new Promise((resolve) => requestAnimationFrame(resolve))
  }

  window.scrollBy({ top: step, behavior: 'smooth' })
}

/** Whether a page's workspace tab strip is resting at the bottom edge of the screen.

Read from the strip's own box against the viewport's client height, which excludes the
horizontal scrollbar band the sticky strip pins above, and re-measured on scroll, on resize,
whenever the page's own size changes, and as the strip appears.
*/
export function useStripDocked(element: MaybeRefOrGetter<HTMLElement | null>) {
  const docked = ref(false)
  let scheduled = false

  // One layout read per frame however many triggers fire, so a scroll never pays a forced
  // reflow inside its own handler.
  function measure() {
    if (scheduled) {
      return
    }

    scheduled = true
    requestAnimationFrame(() => {
      scheduled = false

      // The slack covers the fractional pixels browser zoom introduces on both measurements.
      const box = toValue(element)?.getBoundingClientRect()
      docked.value = box != null && box.bottom >= document.documentElement.clientHeight - 2
    })
  }

  useEventListener(window, 'scroll', measure, { passive: true })
  useEventListener(window, 'resize', measure)
  useResizeObserver(document.body, measure)
  watch(
    () => toValue(element),
    async () => {
      await nextTick()
      measure()
    },
    { immediate: true }
  )

  return docked
}

export type TabSet = Zod.infer<typeof TabSetModel>
export const TabSetModel = Zod.object({
  open: Zod.array(Zod.string()).catch(() => []),
  closed: Zod.array(Zod.string()).catch(() => []),
})

export const TabSetsModel = Zod.record(Zod.string(), TabSetModel).catch(() => ({}))

/** Name of the setting holding every strip's tab set, keyed by placement.

One setting rather than one per strip because setting names are validated as `Name`, which admits
neither the `:` a per-strip name would need nor the `.` a component address uses. A per-strip name
would be writable and not readable. Keying by placement inside a single value keeps every
semantic and reads every strip in one request.
*/
export const tabsSettingName = 'workspaces'

const emptySet: TabSet = { open: [], closed: [] }

/** Name a strip's address carries when it is asking for workspaces to be shown. */
export const workspaceQueryKey = 'workspace'

/** Workspaces the address is asking a page to show, which may name more than one.

The address asks rather than records. A page reads this on arrival, opens what it names, and
removes it from the bar so a stale address never contradicts later changes to the strip. Links
are made deliberately, by the share actions.
*/
export function requestedWorkspaces(query: LocationQuery): string[] {
  const value = query[workspaceQueryKey]
  if (typeof value === 'string') {
    return [value]
  }

  if (Array.isArray(value)) {
    return value.filter((current): current is string => typeof current === 'string')
  }

  return []
}

/** Resolve a strip's effective tabs from its defaults and the user's set.

The result is `(defaults - closed) + open`, ordered by `open` first and then by whatever defaults
remain, in the order they were given. Identifiers resolve against `pool` and are never repaired, so
a workspace the user has lost access to drops off the strip and returns if access is restored, and
a deleted one is ignored.

`identify` reads an item's identifier, keeping this independent of the tab type.

`pool` is what identifiers resolve against, defaulting to the defaults themselves. The home strip
passes every workspace the user can see because a workspace placed on a component may be opened
there while never belonging to the engine root's defaults.
*/
export function resolveTabs<T>(
  defaults: T[],
  set: TabSet,
  identify: (item: T) => string,
  pool: T[] = defaults
): T[] {
  const byId = new Map(pool.map((item) => [identify(item), item]))
  const closed = new Set(set.closed)

  const opened = set.open.map((id) => byId.get(id)).filter((item): item is T => item !== undefined)

  const openedIds = new Set(opened.map(identify))
  const remaining = defaults.filter(
    (item) => !openedIds.has(identify(item)) && !closed.has(identify(item))
  )

  return [...opened, ...remaining]
}

/** Remember which workspace a strip last showed so returning to it lands where it was left.

Held per device rather than in the tab set because that set is a single record covering every
placement and would be rewritten in full on each tab click. Which tab you were last on is a
browsing position rather than a preference so it belongs with the rest of the local view state.

An identifier is remembered rather than a position so a workspace that moves in the strip is
still the one that reopens, and one that is closed or lost falls back to the first tab.
*/
export function useLastWorkspace(placement: MaybeRefOrGetter<string>) {
  return usePersisted({
    schema: ({ object, string }) => object({ id: string().nullable().default(null) }),
    methods: computed(() => [
      { type: 'local-storage' as const, key: ['workspace-tabs-last', toValue(placement)] },
    ]),
  })
}

export const useTabs = defineStore('tabs', () => {
  const settings = useSettings()
  let sets = $ref<Record<string, TabSet>>({})
  let loaded = $ref(false)

  /** Read every strip's set once. A user who has never arranged a strip has no setting at all,
  which the API reports as missing rather than as empty so that case is the starting state and
  not a failure.
  */
  async function load() {
    if (loaded) {
      return
    }

    try {
      sets = (await settings.get(tabsSettingName, TabSetsModel)) ?? {}
    } catch (error) {
      sets = {}
    }

    loaded = true
  }

  function setFor(placement: string): TabSet {
    return sets[placement] ?? emptySet
  }

  function isTouched(placement: string): boolean {
    return sets[placement] !== undefined
  }

  async function write(placement: string, set: TabSet) {
    sets = { ...sets, [placement]: set }
    await settings.set(tabsSettingName, sets)
  }

  // Opening clears any record of the workspace having been closed so the two lists never
  // disagree about one workspace.
  async function open(placement: string, id: string) {
    const set = setFor(placement)
    if (set.open.includes(id)) {
      return
    }

    await write(placement, {
      open: [...set.open, id],
      closed: set.closed.filter((current) => current !== id),
    })
  }

  // Closing records the identifier rather than only dropping it from `open` because a workspace
  // that is one of the defaults would otherwise reappear the moment anything else changed.
  async function close(placement: string, id: string) {
    await closeMany(placement, [id])
  }

  // Opening and closing several at once are single writes rather than one per workspace, because
  // every write sends the whole record for every strip.
  async function openMany(placement: string, ids: string[]) {
    const set = setFor(placement)
    const added = ids.filter((id) => !set.open.includes(id))
    if (added.length === 0) {
      return
    }

    await write(placement, {
      open: [...set.open, ...added],
      closed: set.closed.filter((current) => !ids.includes(current)),
    })
  }

  async function closeMany(placement: string, ids: string[]) {
    const set = setFor(placement)
    const closing = new Set(ids)

    await write(placement, {
      open: set.open.filter((current) => !closing.has(current)),
      closed: [...new Set([...set.closed, ...ids])],
    })
  }

  /** Put a workspace on the strip at a given position.

  The resolved order is passed in because it depends on the strip's defaults, which the set itself
  does not hold. Positioning between two tabs means naming every position, exactly as dragging one
  does so this writes the whole order rather than appending.
  */
  async function openAt(placement: string, id: string, resolved: string[], index: number) {
    const ids = resolved.filter((current) => current !== id)
    ids.splice(Math.max(0, Math.min(index, ids.length)), 0, id)
    await reorder(placement, ids)
  }

  /** Put a workspace on the strip directly after another one.

  Falling back to opening at the end covers the workspace it was to sit beside not being on the
  strip at all, in which case there is no beside to speak of.
  */
  async function openBeside(placement: string, id: string, afterId: string, resolved: string[]) {
    const others = resolved.filter((current) => current !== id)
    const index = others.indexOf(afterId)
    if (index < 0) {
      await open(placement, id)
      return
    }

    await openAt(placement, id, others, index + 1)
  }

  // Dragging a tab positions every tab in the strip so the whole resolved order becomes explicit.
  async function reorder(placement: string, ids: string[]) {
    const set = setFor(placement)
    await write(placement, {
      open: ids,
      closed: set.closed.filter((current) => !ids.includes(current)),
    })
  }

  // A first login inherits a starting set. A strip the user has already arranged is theirs, so
  // seeding never overwrites one.
  async function seed(placement: string, ids: string[]) {
    if (isTouched(placement)) {
      return
    }

    await write(placement, { open: ids, closed: [] })
  }

  return {
    load,
    setFor,
    isTouched,
    open,
    openAt,
    openBeside,
    openMany,
    close,
    closeMany,
    reorder,
    seed,
  }
})
