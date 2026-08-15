import type { Status } from '@/api/statuses'

/** A component a status badge covers, and whether the user may act on it. */
export type StatusSubject = {
  status: Status | null
  operable: boolean
}

/** What a status badge reports about everything it covers. */
export type StatusCounts = {
  running: number
  stopped: number
  enabled: number
  disabled: number
  total: number
  anyRunning: boolean
  anyEnabled: boolean
  allRunning: boolean
  someRunning: boolean
  allEnabled: boolean
  someEnabled: boolean
}

/** Tally `subjects` into the counts a status badge shows.

The counts cover only components the user may operate, since they say what an action would
affect. The `any` flags cover everything in scope, so a badge over components the user can only
look at still reports whether any of them is running.
*/
export function countStatuses(subjects: StatusSubject[]): StatusCounts {
  let running = 0
  let enabled = 0
  let total = 0
  let anyRunning = false
  let anyEnabled = false

  for (const { status, operable } of subjects) {
    if (status == null) {
      continue
    }

    anyRunning ||= status.running
    anyEnabled ||= status.enabled === true

    if (!operable) {
      continue
    }

    total++
    if (status.running) {
      running++
    }

    if (status.enabled === true) {
      enabled++
    }
  }

  return {
    running,
    stopped: total - running,
    enabled,
    disabled: total - enabled,
    total,
    anyRunning,
    anyEnabled,
    allRunning: total > 0 && running === total,
    someRunning: running > 0,
    allEnabled: total > 0 && enabled === total,
    someEnabled: enabled > 0,
  }
}

/** How many components a count refers to, for a message naming what an action affected. */
export function componentCount(total: number): string {
  return `${total} component${total === 1 ? '' : 's'}`
}
