import { isEqual } from 'lodash-es'
import { shallowReactive } from 'vue'

/** Where a history keeps its entries, reactive so a caller can persist it. */
export interface ValueHistoryState<T> {
  entries: T[]
  /** The current entry's index, -1 while there are no entries. */
  index: number
}

export interface ValueHistoryOptions<T> {
  /** The most entries kept, the oldest dropped first. */
  limit: number
  equal?: (left: T, right: T) => boolean
  /** Copies a value going in or coming out, so a later change to it never rewrites an entry. */
  clone?: (value: T) => T
  /** The state to keep entries in, a fresh one held in memory when omitted. */
  state?: ValueHistoryState<T>
}

/** A linear history of values with a current entry, like a browser's Back and Forward. */
export interface ValueHistory<T> {
  readonly canBack: boolean
  readonly canForward: boolean
  /** Makes `value` the current entry and drops every entry ahead of it. A value equal to the
  current entry changes nothing, so going back or forward and writing the result never records it
  again. */
  record: (value: T) => void
  /** Puts `value` in place of the current entry, keeping the entries around it. */
  replace: (value: T) => void
  back: () => T | undefined
  forward: () => T | undefined
  /** Starts over with `value` as the only entry. */
  reset: (value: T) => void
  clear: () => void
}

export function createHistory<T>({
  limit,
  equal = isEqual,
  clone = (value) => value,
  state = shallowReactive<ValueHistoryState<T>>({ entries: [], index: -1 }),
}: ValueHistoryOptions<T>): ValueHistory<T> {
  // A stored state may come back out of range, so every read clamps the index to the entries.
  const index = () => Math.min(state.index, state.entries.length - 1)

  function move(step: number) {
    const current = index()
    const target = current + step
    if (current < 0 || target < 0 || target >= state.entries.length) {
      return undefined
    }

    state.index = target
    return clone(state.entries[target]!)
  }

  function reset(value: T) {
    state.entries = [clone(value)]
    state.index = 0
  }

  return {
    get canBack() {
      return index() > 0
    },
    get canForward() {
      const current = index()
      return current >= 0 && current < state.entries.length - 1
    },
    record(value) {
      const current = index()
      if (current >= 0 && equal(value, state.entries[current]!)) {
        return
      }

      const kept = [
        ...state.entries.slice(Math.max(0, current + 2 - limit), current + 1),
        clone(value),
      ]
      state.entries = kept
      state.index = kept.length - 1
    },
    replace(value) {
      const current = index()
      if (current < 0) {
        reset(value)
      } else {
        state.entries = state.entries.with(current, clone(value))
      }
    },
    back: () => move(-1),
    forward: () => move(1),
    reset,
    clear() {
      state.entries = []
      state.index = -1
    },
  }
}
