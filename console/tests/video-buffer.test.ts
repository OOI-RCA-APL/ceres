import { describe, expect, it } from 'vitest'

import { keptSeconds } from '@/video-buffer'

describe('keptSeconds', () => {
  it('keeps what fits in 50 MB', () => {
    // A 1080p stream at 10 Mbit/s.
    expect(keptSeconds(1_250_000)).toBe(40)
  })

  it('keeps at least ten seconds of a heavy stream', () => {
    expect(keptSeconds(50_000_000)).toBe(10)
  })

  it('keeps at most five minutes of a light stream', () => {
    expect(keptSeconds(10_000)).toBe(300)
  })

  it('keeps the most while the bitrate is unknown', () => {
    expect(keptSeconds(0)).toBe(300)
  })
})
