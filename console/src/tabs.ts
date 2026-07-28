import { defineStore } from 'pinia'
import Zod from 'zod'

import { useSettings } from '@/api/settings'

export type TabSet = Zod.infer<typeof TabSetModel>
export const TabSetModel = Zod.object({
  open: Zod.array(Zod.string()).catch(() => []),
  closed: Zod.array(Zod.string()).catch(() => []),
})

export const TabSetsModel = Zod.record(Zod.string(), TabSetModel).catch(() => ({}))

/** Name of the setting holding every strip's tab set, keyed by placement.

One setting rather than one per strip, because setting names are validated as `Name`, which admits
neither the `:` a per-strip name would need nor the `.` a component address uses. A per-strip name
would be writable and not readable. Keying by placement inside a single value keeps every
semantic and reads every strip in one request.
*/
export const tabsSettingName = 'workspaces'

const emptySet: TabSet = { open: [], closed: [] }

/** Resolve a strip's effective tabs from its defaults and the user's set.

The result is `(defaults - closed) + open`, ordered by `open` first and then by whatever defaults
remain, in the order they were given. Identifiers resolve against `pool` and are never repaired, so
a workspace the user has lost access to drops off the strip and returns if access is restored, and
a deleted one is ignored.

`identify` reads an item's identifier, so this stays independent of what a tab happens to be.

`pool` is what identifiers resolve against, defaulting to the defaults themselves. The home strip
passes every workspace the user can see, because a workspace placed on a component may be opened
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

export const useTabs = defineStore('tabs', () => {
  const settings = useSettings()
  let sets = $ref<Record<string, TabSet>>({})
  let loaded = $ref(false)

  /** Read every strip's set once. A user who has never arranged a strip has no setting at all,
  which the API reports as missing rather than as empty, so that case is the starting state and
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

  // Opening clears any record of the workspace having been closed, so the two lists never
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

  // Closing records the identifier rather than only dropping it from `open`, because a workspace
  // that is one of the defaults would otherwise reappear the moment anything else changed.
  async function close(placement: string, id: string) {
    const set = setFor(placement)
    await write(placement, {
      open: set.open.filter((current) => current !== id),
      closed: set.closed.includes(id) ? set.closed : [...set.closed, id],
    })
  }

  // Dragging a tab positions every tab in the strip, so the whole resolved order becomes explicit.
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

  return { load, setFor, isTouched, open, close, reorder, seed }
})
