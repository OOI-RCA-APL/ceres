import { onScopeDispose, reactive } from 'vue'

export interface ReconnectOptions {
  /** Seconds between attempts after the first, which goes at once. */
  interval?: number
  /** Seconds an attempt gets to bring data before it counts as lost too. */
  timeout?: number
}

export interface ReconnectSchedule {
  /** Seconds until the next attempt while waiting between attempts, otherwise `null`. */
  readonly countdown: number | null
  /** Whether the connection was lost and has not come back yet. */
  readonly isReconnecting: boolean
  /** Count an attempt as begun, so it is lost if no data comes within the timeout. */
  begin(): void
  /** Report the connection lost, which schedules the next attempt. */
  lost(): void
  /** Report data flowing again, which ends any reconnecting and resets the schedule. */
  recovered(): void
  /** Stop every timer, for good or until the next `begin` or `lost`. */
  stop(): void
}

// A loss reported this soon after an attempt began is the old connection's last word, an error
// and an `ended` from the same drop say, and not the new attempt failing.
const SETTLE_MS = 1000

/** Retries a lost connection at once, then every `interval` seconds until data flows again. An
attempt that brings no data within `timeout` seconds counts as lost as well. */
export function useReconnectSchedule(
  retry: () => void,
  { interval = 5, timeout = 15 }: ReconnectOptions = {},
): ReconnectSchedule {
  let tick: ReturnType<typeof setInterval> | null = null
  let deadline: ReturnType<typeof setTimeout> | null = null
  let attemptStartedAt = -Infinity

  function clearTimers() {
    if (tick != null) {
      clearInterval(tick)
      tick = null
    }
    if (deadline != null) {
      clearTimeout(deadline)
      deadline = null
    }
  }

  function begin() {
    if (deadline != null) {
      clearTimeout(deadline)
    }
    deadline = setTimeout(() => {
      deadline = null
      schedule.lost()
    }, timeout * 1000)
  }

  function attempt() {
    schedule.countdown = null
    attemptStartedAt = Date.now()
    begin()
    retry()
  }

  const schedule = reactive({
    countdown: null as number | null,
    isReconnecting: false,

    begin,

    lost() {
      if (schedule.countdown != null || Date.now() - attemptStartedAt < SETTLE_MS) {
        return
      }
      clearTimers()

      if (!schedule.isReconnecting) {
        schedule.isReconnecting = true
        attempt()
        return
      }

      schedule.countdown = interval
      tick = setInterval(() => {
        schedule.countdown = (schedule.countdown ?? 1) - 1
        if (schedule.countdown <= 0) {
          clearTimers()
          attempt()
        }
      }, 1000)
    },

    recovered() {
      clearTimers()
      attemptStartedAt = -Infinity
      schedule.countdown = null
      schedule.isReconnecting = false
    },

    stop() {
      clearTimers()
      schedule.countdown = null
    },
  })

  onScopeDispose(() => schedule.stop(), true)

  return schedule
}
