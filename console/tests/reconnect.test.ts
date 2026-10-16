import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { effectScope } from 'vue'

import { useReconnectSchedule } from '@/reconnect'

function schedule(options?: { interval?: number; timeout?: number }) {
  const retry = vi.fn()
  const scope = effectScope()
  const reconnect = scope.run(() => useReconnectSchedule(retry, options))!
  return { retry, reconnect, scope }
}

describe('reconnecting a lost stream', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('retries at once, then every five seconds with a countdown', () => {
    const { retry, reconnect } = schedule()

    reconnect.lost()
    expect(retry).toHaveBeenCalledTimes(1)
    expect(reconnect.isReconnecting).toBe(true)
    expect(reconnect.countdown).toBeNull()

    // The first attempt fails too.
    vi.advanceTimersByTime(2000)
    reconnect.lost()
    expect(reconnect.countdown).toBe(5)

    vi.advanceTimersByTime(1000)
    expect(reconnect.countdown).toBe(4)
    vi.advanceTimersByTime(4000)
    expect(retry).toHaveBeenCalledTimes(2)
    expect(reconnect.countdown).toBeNull()

    vi.advanceTimersByTime(2000)
    reconnect.lost()
    vi.advanceTimersByTime(5000)
    expect(retry).toHaveBeenCalledTimes(3)
  })

  it('counts an attempt bringing nothing within the timeout as lost', () => {
    const { retry, reconnect } = schedule({ interval: 5, timeout: 15 })

    reconnect.lost()
    vi.advanceTimersByTime(15000)
    expect(reconnect.countdown).toBe(5)
    vi.advanceTimersByTime(5000)
    expect(retry).toHaveBeenCalledTimes(2)
  })

  it('treats a second report of the same drop as one loss', () => {
    const { retry, reconnect } = schedule()

    reconnect.lost()
    reconnect.lost()
    expect(retry).toHaveBeenCalledTimes(1)
    expect(reconnect.countdown).toBeNull()
  })

  it('ignores losses while already counting down', () => {
    const { retry, reconnect } = schedule()

    reconnect.lost()
    vi.advanceTimersByTime(2000)
    reconnect.lost()
    vi.advanceTimersByTime(2000)
    reconnect.lost()
    expect(reconnect.countdown).toBe(3)
    vi.advanceTimersByTime(3000)
    expect(retry).toHaveBeenCalledTimes(2)
  })

  it('starts over once data flows again', () => {
    const { retry, reconnect } = schedule()

    reconnect.lost()
    vi.advanceTimersByTime(2000)
    reconnect.recovered()
    expect(reconnect.isReconnecting).toBe(false)

    // The next drop is retried at once again, and the old attempt's deadline is gone.
    vi.advanceTimersByTime(60000)
    expect(retry).toHaveBeenCalledTimes(1)
    reconnect.lost()
    expect(retry).toHaveBeenCalledTimes(2)
  })

  it('gives a first connection the same deadline', () => {
    const { retry, reconnect } = schedule()

    reconnect.begin()
    vi.advanceTimersByTime(15000)
    expect(retry).toHaveBeenCalledTimes(1)
  })

  it('stops every timer when stopped or disposed', () => {
    const { retry, reconnect, scope } = schedule()

    reconnect.lost()
    vi.advanceTimersByTime(2000)
    reconnect.lost()
    reconnect.stop()
    expect(reconnect.countdown).toBeNull()
    vi.advanceTimersByTime(60000)
    expect(retry).toHaveBeenCalledTimes(1)

    reconnect.begin()
    scope.stop()
    vi.advanceTimersByTime(60000)
    expect(retry).toHaveBeenCalledTimes(1)
  })
})
