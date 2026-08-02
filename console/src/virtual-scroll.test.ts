import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { onceAFrame } from '@/virtual-scroll'

/** A listener shaped the way Quasar's debounced ones are, counting what reaches its payload.

It schedules through `globalThis` for the same reason Quasar's unqualified call resolves there,
which is what lets the work it puts off be taken over.
*/
function debouncedListener(wait: number = 35) {
  const payload = vi.fn()
  let timer: ReturnType<typeof setTimeout> | null = null

  const listener = Object.assign(
    () => {
      if (timer !== null) {
        clearTimeout(timer)
      }

      timer = globalThis.setTimeout(() => {
        timer = null
        payload()
      }, wait)
    },
    { cancel: () => timer !== null && clearTimeout(timer) }
  )

  return { listener, payload }
}

/** A listener that puts nothing off, which is not a shape whose work can be taken over. */
function plainListener() {
  const payload = vi.fn()
  return { listener: Object.assign(payload, { cancel: () => {} }), payload }
}

const scroll = new Event('scroll')

describe('a scroller being scrolled', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('draws on the very first scroll, without waiting out the delay at all', () => {
    const { listener, payload } = debouncedListener()
    const scrolling = onceAFrame(listener)

    scrolling(scroll)

    // No time has passed, so the work the listener put off was taken over rather than waited for.
    expect(payload).toHaveBeenCalledTimes(1)
  })

  it('draws during the scrolling rather than only once it stops', () => {
    const { listener, payload } = debouncedListener()
    const scrolling = onceAFrame(listener)

    // A scroll every 10ms, sooner than the 35ms this listener waits out, so left to itself it
    // would start that wait again every time and never draw at all.
    for (let tick = 0; tick < 40; tick++) {
      scrolling(scroll)
      vi.advanceTimersByTime(10)
    }

    expect(payload.mock.calls.length).toBeGreaterThan(3)
  })

  it('draws for every scroll it is told about, holding nothing back', () => {
    const { listener, payload } = debouncedListener()
    const scrolling = onceAFrame(listener)

    // A browser fires at most one of these per frame, so a gate here could only ever draw less
    // often than asked and never more often than there is a frame to draw into.
    for (let tick = 0; tick < 20; tick++) {
      scrolling(scroll)
    }

    expect(payload).toHaveBeenCalledTimes(20)
  })

  it('holds back only a listener whose own delay has to be given room to elapse', () => {
    const { listener, payload } = plainListener()
    const scrolling = onceAFrame(listener)

    for (let tick = 0; tick < 20; tick++) {
      scrolling(scroll)
    }

    expect(payload.mock.calls.length).toBeLessThanOrEqual(2)
  })

  it('draws once more after the last scroll of all, and then goes quiet', () => {
    const { listener, payload } = debouncedListener()
    const scrolling = onceAFrame(listener)

    scrolling(scroll)
    scrolling(scroll)
    vi.advanceTimersByTime(1000)
    const drawn = payload.mock.calls.length

    vi.advanceTimersByTime(1000)

    // The one still owed was drawn, so what was on screen matches where the scroll ended.
    expect(drawn).toBeGreaterThanOrEqual(2)
    expect(payload.mock.calls.length).toBe(drawn)
  })

  it('leaves a listener that puts nothing off to be called as it always was', () => {
    const { listener, payload } = plainListener()
    const scrolling = onceAFrame(listener)

    scrolling(scroll)
    vi.advanceTimersByTime(1000)
    scrolling(scroll)
    vi.advanceTimersByTime(1000)

    expect(payload.mock.calls.length).toBeGreaterThanOrEqual(2)
  })

  it('keeps drawing a listener whose work could not be taken over', () => {
    const { listener, payload } = plainListener()
    const scrolling = onceAFrame(listener)

    for (let tick = 0; tick < 40; tick++) {
      scrolling(scroll)
      vi.advanceTimersByTime(10)
    }

    expect(payload.mock.calls.length).toBeGreaterThan(3)
  })
})
