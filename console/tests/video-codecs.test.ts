import { describe, expect, it } from 'vitest'

import { videoCodec } from '@/video-codecs'

describe('videoCodec', () => {
  it('names H.265 with advice for either sample entry', () => {
    expect(videoCodec('hvc1.1.6.L93.B0').name).toBe('H.265 (HEVC)')
    expect(videoCodec('hev1.1.6.L93.B0').advice).toContain('HEVC Video Extension')
  })

  it('names the video codec past an audio one', () => {
    expect(videoCodec('mp4a.40.2, avc1.42E01E')).toEqual({ name: 'H.264' })
  })

  it('falls back to the sample entry for a codec it does not know', () => {
    expect(videoCodec('abcd.1')).toEqual({ name: 'abcd' })
  })
})
