// A `MediaSource` buffer is created for one codec, named the way RFC 6381 spells it, and a browser
// refuses a buffer whose codec does not match the stream. An MP4 response names only `video/mp4`,
// so the codec is read from the stream's own init segment, the `moov` box at its start.

/** What the start of an MP4 stream says about its codecs. */
export type InitSegment =
  /** The `moov` box has not fully arrived, so more bytes are needed. */
  | { type: 'partial' }
  /**
   * The `codecs` parameter for a `MediaSource` buffer, such as `hvc1.1.6.L120.90`, and the length
   * in seconds the stream declares, `null` when it declares none, as a live stream cannot.
   */
  | { type: 'codecs'; codecs: string; duration: number | null }
  /** The stream is not a fragmented MP4 a `MediaSource` takes, or its codec is not known here. */
  | { type: 'unknown' }

// Past this many bytes with no `moov` box the stream is not one worth waiting on.
const maxInitSegmentBytes = 4 * 1024 * 1024

// The bytes in a visual sample entry ahead of its child boxes, ISO/IEC 14496-12 12.1.3.
const visualSampleEntryBytes = 78
// The bytes in an audio sample entry ahead of its child boxes, ISO/IEC 14496-12 12.2.3.
const audioSampleEntryBytes = 28

interface Box {
  type: string
  /** The box's content, past its header. */
  body: Uint8Array
}

/** The boxes laid end to end in `bytes`, stopping at the first one cut short. */
function* boxes(bytes: Uint8Array): Generator<Box | 'partial'> {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength)
  let offset = 0
  while (offset + 8 <= bytes.length) {
    let size = view.getUint32(offset)
    let header = 8
    if (size === 1) {
      if (offset + 16 > bytes.length) {
        yield 'partial'
        return
      }
      size = Number(view.getBigUint64(offset + 8))
      header = 16
    } else if (size === 0) {
      size = bytes.length - offset
    }

    if (size < header) {
      return
    }
    if (offset + size > bytes.length) {
      yield 'partial'
      return
    }

    const type = String.fromCharCode(...bytes.subarray(offset + 4, offset + 8))
    yield { type, body: bytes.subarray(offset + header, offset + size) }
    offset += size
  }

  if (offset < bytes.length) {
    yield 'partial'
  }
}

/** The first complete child of `bytes` with `type`, or `null`. */
function child(bytes: Uint8Array, type: string) {
  for (const box of boxes(bytes)) {
    if (box !== 'partial' && box.type === type) {
      return box.body
    }
  }

  return null
}

/** The child of `bytes` at the end of `path`, or `null` when any step is missing. */
function descend(bytes: Uint8Array, path: string[]) {
  let current: Uint8Array | null = bytes
  for (const type of path) {
    current = current == null ? null : child(current, type)
  }

  return current
}

function hex(byte: number) {
  return byte.toString(16).toUpperCase().padStart(2, '0')
}

/** `avc1.PPCCLL` from an `avcC` box, ISO/IEC 14496-15 5.3.3.1. */
function avcCodec(type: string, config: Uint8Array) {
  if (config.length < 4) {
    return null
  }

  return `${type}.${hex(config[1]!)}${hex(config[2]!)}${hex(config[3]!)}`
}

/** `hvc1.1.6.L120.90` and the like from an `hvcC` box, ISO/IEC 14496-15 E.3. */
function hevcCodec(type: string, config: Uint8Array) {
  if (config.length < 13) {
    return null
  }

  const view = new DataView(config.buffer, config.byteOffset, config.byteLength)
  const profileByte = config[1]!
  const space = ['', 'A', 'B', 'C'][profileByte >> 6]
  const tier = (profileByte >> 5) & 1 ? 'H' : 'L'
  const profile = profileByte & 0x1f
  // The compatibility flags are written in reverse bit order.
  let flags = view.getUint32(2)
  let reversed = 0
  for (let bit = 0; bit < 32; bit++) {
    reversed = (reversed << 1) | (flags & 1)
    flags >>>= 1
  }
  const constraints = [...config.subarray(6, 12)]
  while (constraints.length > 0 && constraints.at(-1) === 0) {
    constraints.pop()
  }
  const level = config[12]!

  return [
    type,
    `${space}${profile}`,
    (reversed >>> 0).toString(16).toUpperCase(),
    `${tier}${level}`,
    ...constraints.map(hex),
  ].join('.')
}

/** The codec of one sample entry, or `null` when it is not one known here. */
function sampleEntryCodec(entry: Box) {
  switch (entry.type) {
    case 'avc1':
    case 'avc3': {
      const config = child(entry.body.subarray(visualSampleEntryBytes), 'avcC')
      return config == null ? null : avcCodec(entry.type, config)
    }
    case 'hvc1':
    case 'hev1': {
      const config = child(entry.body.subarray(visualSampleEntryBytes), 'hvcC')
      return config == null ? null : hevcCodec(entry.type, config)
    }
    case 'mp4a':
      // AAC-LC, the AAC that live MP4 audio almost always is. The exact object type would
      // take the `esds` descriptor, and browsers decode any AAC under this name.
      return entry.body.length >= audioSampleEntryBytes ? 'mp4a.40.2' : null
    default:
      return null
  }
}

/** A full box's version and the unsigned integer `offset` bytes past it, 32 bits in version 0 and
64 in version 1, or `null` when the box is too short. */
function versioned(body: Uint8Array, offset: { 0: number; 1: number }) {
  const version = body[0]
  if (version !== 0 && version !== 1) {
    return null
  }

  const at = offset[version]
  const bytes = version === 0 ? 4 : 8
  if (body.length < at + bytes) {
    return null
  }

  const view = new DataView(body.buffer, body.byteOffset, body.byteLength)
  return version === 0 ? view.getUint32(at) : Number(view.getBigUint64(at))
}

/**
 * The length in seconds a fragmented `moov` declares, or `null` when it declares none.
 *
 * A fragmented MP4 written as it is recorded, live video above all, knows no length when it
 * writes its `moov`, so its `mvhd` says 0 and it has no `mehd`, ISO/IEC 14496-12 8.8.2. Browsers
 * disagree on what that means: Chrome reports an infinite duration, Safari a finite one.
 */
function declaredDuration(moov: Uint8Array) {
  const mvhd = child(moov, 'mvhd')
  // The time scale follows the version, flags and two timestamps, the duration the time scale.
  const timescale = mvhd == null ? null : versioned(mvhd, { 0: 12, 1: 20 })
  if (mvhd == null || timescale == null || timescale === 0) {
    return null
  }

  const mehd = descend(moov, ['mvex', 'mehd'])
  const length = mehd == null ? versioned(mvhd, { 0: 16, 1: 24 }) : versioned(mehd, { 0: 4, 1: 4 })

  return length == null || length === 0 ? null : length / timescale
}

/** Read the codecs from the start of a fragmented MP4 stream. */
export function readInitSegment(bytes: Uint8Array): InitSegment {
  for (const box of boxes(bytes)) {
    if (box === 'partial') {
      return bytes.length > maxInitSegmentBytes ? { type: 'unknown' } : { type: 'partial' }
    }

    if (box.type === 'moov') {
      // Only a fragmented MP4 carries `mvex`, and a plain one cannot be fed in pieces.
      if (child(box.body, 'mvex') == null) {
        return { type: 'unknown' }
      }

      const codecs: string[] = []
      for (const trak of boxes(box.body)) {
        if (trak === 'partial' || trak.type !== 'trak') {
          continue
        }

        const stsd = descend(trak.body, ['mdia', 'minf', 'stbl', 'stsd'])
        // A full box with a version, flags and an entry count ahead of its entries.
        const entry = stsd == null ? null : boxes(stsd.subarray(8)).next().value
        const codec = entry == null || entry === 'partial' ? null : sampleEntryCodec(entry)
        if (codec == null) {
          return { type: 'unknown' }
        }
        codecs.push(codec)
      }

      return codecs.length === 0
        ? { type: 'unknown' }
        : { type: 'codecs', codecs: codecs.join(', '), duration: declaredDuration(box.body) }
    }

    // Media data or fragments ahead of the `moov` box are not a stream to feed in pieces.
    if (box.type === 'mdat' || box.type === 'moof') {
      return { type: 'unknown' }
    }
  }

  return bytes.length > maxInitSegmentBytes ? { type: 'unknown' } : { type: 'partial' }
}
