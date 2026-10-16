/** A codec a viewer would know by name, for a message saying their browser cannot play it. */
type KnownCodec = {
  /** The name shown, such as `H.265 (HEVC)`. */
  name: string
  /** What a viewer can do about it, where something better than another browser is known. */
  advice?: string
}

// By the sample entry an RFC 6381 codec string starts with.
const knownCodecs: Record<string, KnownCodec> = {
  avc1: { name: 'H.264' },
  avc3: { name: 'H.264' },
  hvc1: {
    name: 'H.265 (HEVC)',
    // Browsers decode it only through the machine's own decoder, and on Windows Edge and Firefox
    // reach that only through Microsoft's extension, which not every PC comes with.
    advice:
      "Safari and Chrome play it on most computers. On Windows, Edge and Firefox also need Microsoft's HEVC Video Extension.",
  },
  av01: { name: 'AV1' },
  vp09: { name: 'VP9' },
}
knownCodecs.hev1 = knownCodecs.hvc1!

/** The video codec of `codecs`, an RFC 6381 list such as `hvc1.1.6.L93.B0, mp4a.40.2`, by the
name a viewer would know it by. Audio is skipped, since a video that will not play is the video's
codec at fault. */
export function videoCodec(codecs: string): KnownCodec {
  const entries = codecs.split(',').map((codec) => codec.trim().split('.')[0]!)
  const video = entries.find((entry) => entry !== 'mp4a' && entry !== 'opus')
  return (video != null ? knownCodecs[video] : undefined) ?? { name: video ?? codecs }
}
