import { shallowReactive } from 'vue'

import type { Record } from '@/api/entity'

export type RecordFeedOptions<TRecord extends Record> = {
  /** Fetch a page of records for a filter, newest first when ordered descending. */
  getAll: (filter: globalThis.Record<string, unknown>) => Promise<TRecord[]>

  /** The compiled filter each fetch sends, read fresh per request. */
  filter: () => globalThis.Record<string, unknown>

  /** How many records a page asks for. */
  pageSize: () => number

  /** The clock, injectable so tests control the rate-limit guards. */
  now?: () => number
}

export type RecordFeed<TRecord extends Record> = ReturnType<typeof createRecordFeed<TRecord>>

/** The data half of a record view: fetching, ordering, and buffering, with no scrolling.

Rows are held oldest to newest. Older pages fetch into a buffer the host places when its
scroller is ready for the list to grow, and live arrivals can be held the same way, so the
geometry stays the host's alone. Every path dedups by record ID: the initial fetch races the
stream, a reconnecting stream replays records, and an older page can share its boundary
timestamp with a record already held.
*/
export function createRecordFeed<TRecord extends Record>(options: RecordFeedOptions<TRecord>) {
  const now = options.now ?? (() => Date.now())

  const rows = shallowReactive<TRecord[]>([])

  /** Older records already fetched and waiting to be placed, oldest first. */
  const previousBuffer: TRecord[] = []

  /** Live arrivals held while the host's scroller is busy. */
  const pendingAppends: TRecord[] = []

  let isLoadingCurrent = $ref(true)
  let isLoadingPrevious = $ref(false)
  let isExhausted = $ref(false)

  let lastLoadedCurrent: number | null = null
  let lastLoadedPrevious: number | null = null

  const heldRecordIds = new Set<string>()

  function rebuildHeldRecordIds() {
    heldRecordIds.clear()
    for (const record of rows) {
      heldRecordIds.add(record.id)
    }
    for (const record of previousBuffer) {
      heldRecordIds.add(record.id)
    }
  }

  /** The records of `incoming` not already held, each counted as held on the way through. */
  function onlyNewRecords(incoming: TRecord[]): TRecord[] {
    const fresh: TRecord[] = []
    for (const record of incoming) {
      if (!heldRecordIds.has(record.id)) {
        heldRecordIds.add(record.id)
        fresh.push(record)
      }
    }

    return fresh
  }

  let buffered = $ref(0)
  let pending = $ref(0)

  function syncCounts() {
    buffered = previousBuffer.length
    pending = pendingAppends.length
  }

  /** Drop everything held, for a filter change or a reload. */
  function reset() {
    rows.splice(0)
    previousBuffer.splice(0)
    pendingAppends.splice(0)
    heldRecordIds.clear()
    isExhausted = false
    isLoadingCurrent = true
    syncCounts()
  }

  /** Append records at the newest end, resorting only when an arrival lands out of order. */
  function append(records: TRecord[]): TRecord[] {
    const fresh = onlyNewRecords(records)
    let resort = false
    if (fresh.length > 0 && rows.length > 0) {
      if (fresh[fresh.length - 1]!.timestamp < rows[rows.length - 1]!.timestamp) {
        resort = true
      }
    }

    rows.push(...fresh)
    if (resort) {
      // Compared directly rather than with localeCompare. These are ISO timestamps so the
      // result is the same either way, and nothing here depends on a locale.
      rows.sort((left, right) =>
        left.timestamp < right.timestamp ? -1 : left.timestamp > right.timestamp ? 1 : 0,
      )
    }

    return fresh
  }

  /** Drop the oldest rows down to `keep`, returning how many went. */
  function cull(keep: number): number {
    const removed = Math.max(0, rows.length - keep)
    if (removed > 0) {
      rows.splice(0, removed)
      rebuildHeldRecordIds()
    }

    return removed
  }

  /** A live arrival, held for later when the host asks. */
  function receive(record: TRecord, hold: boolean): 'appended' | 'held' {
    if (hold || isLoadingCurrent) {
      pendingAppends.push(record)
      syncCounts()
      return 'held'
    }

    append([record])
    return 'appended'
  }

  /** Append everything held, returning what was fresh. */
  function flushPending(): TRecord[] {
    const fresh = append(pendingAppends.splice(0))
    syncCounts()
    return fresh
  }

  /** The oldest record held anywhere, where the next older fetch carries on from. */
  function earliestHeldTimestamp(): string | null {
    return previousBuffer[0]?.timestamp ?? rows[0]?.timestamp ?? null
  }

  /** Load the newest page, replacing everything held. */
  async function loadCurrent() {
    reset()

    const filter = options.filter()
    try {
      const results = await options.getAll({
        ...filter,
        order: 'timestamp:desc',
        limit: options.pageSize(),
      })

      // The filter moved on while this was in flight, so a newer load owns the list.
      if (filter !== options.filter()) {
        return
      }

      isExhausted = results.length === 0
      append([...results.reverse(), ...pendingAppends.splice(0)])
      lastLoadedCurrent = now()
      syncCounts()
    } finally {
      isLoadingCurrent = false
    }
  }

  /** Fetch the page above what is held into the buffer.

  Rate limited so a scroller resting near the top does not hammer the endpoint: nothing
  fetches until a second after the newest load, or within a second of the last older one.
  */
  async function fetchPrevious() {
    if (isExhausted || isLoadingPrevious || previousBuffer.length > 0) {
      return
    }

    if (lastLoadedCurrent == null || now() - lastLoadedCurrent < 1000) {
      return
    }
    if (lastLoadedPrevious != null && now() - lastLoadedPrevious < 1000) {
      return
    }

    isLoadingPrevious = true

    const filter = options.filter()
    try {
      const results = await options.getAll({
        ...filter,
        // Counted from the oldest record held anywhere so what is already waiting in the
        // buffer is not asked for a second time.
        before: earliestHeldTimestamp() ?? filter.before,
        order: 'timestamp:desc',
        limit: options.pageSize(),
      })

      if (filter !== options.filter()) {
        return
      }

      isExhausted = results.length === 0
      const fresh = onlyNewRecords(results.reverse())
      previousBuffer.splice(0, 0, ...fresh)
      lastLoadedPrevious = now()
      syncCounts()
    } finally {
      isLoadingPrevious = false
    }
  }

  /** Put the buffered older records into the list, returning how many for the host's scroll
  compensation. */
  function placePrevious(): number {
    const placed = previousBuffer.splice(0)
    rows.splice(0, 0, ...placed)
    syncCounts()
    return placed.length
  }

  return {
    rows,
    isLoadingCurrent: $$(isLoadingCurrent),
    isLoadingPrevious: $$(isLoadingPrevious),
    isExhausted: $$(isExhausted),
    bufferedCount: $$(buffered),
    pendingCount: $$(pending),
    reset,
    append,
    cull,
    receive,
    flushPending,
    loadCurrent,
    fetchPrevious,
    placePrevious,
  }
}
