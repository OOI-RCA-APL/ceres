import { describe, expect, it } from 'vitest'

import {
  aac,
  avc,
  box,
  hevc,
  initSegment,
  plainInitSegment,
  recordingInitSegment,
} from './mp4-fixture'

import { readInitSegment } from '@/mp4'

describe('readInitSegment', () => {
  it('reads an H.265 stream', () => {
    expect(readInitSegment(initSegment(hevc))).toEqual({
      type: 'codecs',
      codecs: 'hvc1.1.6.L93.B0',
      duration: null,
    })
  })

  it('reads every track', () => {
    expect(readInitSegment(initSegment(avc, aac))).toEqual({
      type: 'codecs',
      codecs: 'avc1.42E01E, mp4a.40.2',
      duration: null,
    })
  })

  it('reads the length a recording declares', () => {
    expect(readInitSegment(recordingInitSegment(60, hevc))).toMatchObject({ duration: 60 })
  })

  it('waits on a `moov` box cut short', () => {
    const bytes = initSegment(hevc)
    expect(readInitSegment(bytes.subarray(0, bytes.length - 1))).toEqual({ type: 'partial' })
  })

  it('refuses a plain MP4', () => {
    expect(readInitSegment(plainInitSegment(hevc))).toEqual({ type: 'unknown' })
  })

  it('refuses media data ahead of the `moov` box', () => {
    expect(readInitSegment(new Uint8Array([...box('mdat'), ...initSegment(hevc)]))).toEqual({
      type: 'unknown',
    })
  })

  it('refuses a codec it does not know', () => {
    expect(readInitSegment(initSegment(box('abcd')))).toEqual({ type: 'unknown' })
  })
})
