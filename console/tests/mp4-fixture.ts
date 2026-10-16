/** An MP4 box of `type` holding `children` laid end to end. */
export function box(type: string, ...children: Uint8Array[]) {
  const size = 8 + children.reduce((total, child) => total + child.length, 0)
  const bytes = new Uint8Array(size)
  new DataView(bytes.buffer).setUint32(0, size)
  bytes.set(
    [...type].map((char) => char.charCodeAt(0)),
    4,
  )
  let offset = 8
  for (const child of children) {
    bytes.set(child, offset)
    offset += child.length
  }
  return bytes
}

/** A track whose one sample entry is `entry`. */
function trak(entry: Uint8Array) {
  const stsd = box('stsd', new Uint8Array([0, 0, 0, 0, 0, 0, 0, 1]), entry)
  return box('trak', box('mdia', box('minf', box('stbl', stsd))))
}

/** The init segment of a fragmented MP4, one track per sample entry. */
export function initSegment(...entries: Uint8Array[]) {
  return new Uint8Array([...box('ftyp'), ...box('moov', box('mvex'), ...entries.map(trak))])
}

/** The same without `mvex`, a plain MP4 that cannot be fed in pieces. */
export function plainInitSegment(...entries: Uint8Array[]) {
  return new Uint8Array([...box('ftyp'), ...box('moov', ...entries.map(trak))])
}

/** A visual sample entry carrying `config`. */
function visual(type: string, config: Uint8Array) {
  return box(type, new Uint8Array(78), config)
}

/** An H.265 Main profile, level 3.1 sample entry, `hvc1.1.6.L93.B0`. */
export const hevc = visual(
  'hvc1',
  box('hvcC', new Uint8Array([1, 0x01, 0x60, 0, 0, 0, 0xb0, 0, 0, 0, 0, 0, 93])),
)

/** An H.264 Baseline, level 3.0 sample entry, `avc1.42E01E`. */
export const avc = visual('avc1', box('avcC', new Uint8Array([1, 0x42, 0xe0, 0x1e])))

/** An AAC sample entry. */
export const aac = box('mp4a', new Uint8Array(28))
