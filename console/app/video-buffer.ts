// How much already played video a `MediaSource` keeps to seek back over is set in bytes, since
// streams differ tenfold in bitrate and the cost is memory: a wall of videos holds this per
// widget, and Chromium refuses a `SourceBuffer` more than about 150 MB.

/** The bytes of played video kept per widget. */
const keptBytes = 50_000_000
/** The least played video kept, however heavy the stream. */
const minKeptSeconds = 10
/** The most played video kept, however light the stream. */
const maxKeptSeconds = 300

/** The seconds of played video to keep from a stream averaging `bytesPerSecond`. */
export function keptSeconds(bytesPerSecond: number) {
  return Math.min(Math.max(keptBytes / bytesPerSecond, minKeptSeconds), maxKeptSeconds)
}
