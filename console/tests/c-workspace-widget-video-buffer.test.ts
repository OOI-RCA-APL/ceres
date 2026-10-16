import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { hevc, initSegment, plainInitSegment } from './mp4-fixture'

import CWorkspaceWidgetVideo from '@/components/c-workspace-widget-video.vue'
import type { WidgetStatus } from '@/widget-status'
import { VideoWidgetModel } from '@/workspace/models'

vi.mock('@/api/engine', () => ({
  useEngine: () => ({
    components: {
      get: () => ({
        procedures: [
          { name: 'video', type: 'query', output: { type: 'streaming', media: 'video/mp4' } },
        ],
      }),
    },
  }),
}))

vi.mock('@/workspace', () => ({
  useWorkspace: () => ({ resolveAddress: (raw: string) => raw }),
}))

vi.mock('@/environment', () => ({ isMediaSourceSupported: true }))

/** A source buffer holding one second of video per appended chunk. */
class FakeSourceBuffer extends EventTarget {
  start = 0
  end = 0
  removed: [number, number][] = []
  type: string

  constructor(type: string) {
    super()
    this.type = type
  }

  get buffered() {
    const { start, end } = this
    return { length: end > start ? 1 : 0, start: () => start, end: () => end }
  }

  appendBuffer() {
    this.end += 1
    queueMicrotask(() => this.dispatchEvent(new Event('updateend')))
  }

  remove(start: number, end: number) {
    this.removed.push([start, end])
    this.start = end
    queueMicrotask(() => this.dispatchEvent(new Event('updateend')))
  }
}

let buffer: FakeSourceBuffer | null
let isTypeSupported: (type: string) => boolean
let mediaSources: FakeMediaSource[]

class FakeMediaSource extends EventTarget {
  static isTypeSupported = (type: string) => isTypeSupported(type)
  readyState = 'open'
  endOfStream = vi.fn(() => {
    this.readyState = 'ended'
  })

  constructor() {
    super()
    mediaSources.push(this)
  }

  addSourceBuffer(type: string) {
    buffer = new FakeSourceBuffer(type)
    return buffer
  }

  override addEventListener(...args: Parameters<EventTarget['addEventListener']>) {
    super.addEventListener(...args)
    if (args[0] === 'sourceopen') {
      queueMicrotask(() => this.dispatchEvent(new Event('sourceopen')))
    }
  }
}

/** The status the widget last sent up for its header. */
function status(video: VueWrapper) {
  return video.emitted<[WidgetStatus | null]>('status')?.at(-1)?.[0]
}

/** Let every pending promise and microtask run. */
async function settle() {
  for (let index = 0; index < 20; index++) {
    await flushPromises()
  }
}

/** Mount the widget on a stream opening with `head`, whose later chunks the test sends. */
async function streamed(head: Uint8Array) {
  let controller!: ReadableStreamDefaultController<Uint8Array>
  let calls = 0
  const body = new ReadableStream<Uint8Array>({
    start(current) {
      controller = current
      current.enqueue(head)
    },
  })
  vi.stubGlobal(
    'fetch',
    vi.fn(
      async () =>
        // A reconnect gets a stream that never sends, so a test sees only the first.
        new Response(calls++ === 0 ? body : new ReadableStream(), {
          headers: { 'content-type': 'video/mp4' },
        }),
    ),
  )

  const widget = VideoWidgetModel.parse({
    id: 'video',
    type: 'video',
    query: '@device::queries::video',
  })
  const video = mount(CWorkspaceWidgetVideo, {
    props: { widget },
    global: {
      stubs: {
        'c-text': true,
        'c-button': true,
        'c-tooltip': true,
        'c-icon': true,
        'c-widget-status': true,
        'c-video-controls': true,
      },
    },
  })
  const element = video.find('video').element as HTMLVideoElement
  await settle()

  return {
    video,
    element,
    /** Send `count` more chunks of `bytes` each, a second of video apiece, and let the widget
    append them. */
    async send(count: number, bytes = 1) {
      for (let index = 0; index < count; index++) {
        controller.enqueue(new Uint8Array(bytes))
      }
      await settle()
    },
    /** End the response, as the engine does once a recording is all sent. */
    async close() {
      controller.close()
      await settle()
    },
    /** Fail the element with the `MediaError` `code`. */
    async error(code: number) {
      Object.defineProperty(element, 'error', { value: { code, message: '' } })
      await video.find('video').trigger('error')
      await settle()
    },
    /** Load the media's metadata, which reports `duration`. */
    async load(duration: number) {
      Object.defineProperty(element, 'duration', { value: duration })
      await video.find('video').trigger('loadedmetadata')
      await settle()
    },
  }
}

/** Make `element` read as playing at `currentTime`, with everything up to `newest` buffered. */
function playing(element: HTMLVideoElement, currentTime: number, newest: number) {
  const range = { length: 1, start: () => 0, end: () => newest }
  Object.defineProperty(element, 'paused', { value: false })
  Object.defineProperty(element, 'buffered', { value: range })
  Object.defineProperty(element, 'seekable', { value: range })
  Object.defineProperty(element, 'play', { value: async () => {} })
  Object.defineProperty(element, 'getVideoPlaybackQuality', {
    value: () => ({ totalVideoFrames: 1 }),
  })
  element.currentTime = currentTime
}

describe('c-workspace-widget-video through a MediaSource', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    buffer = null
    isTypeSupported = () => true
    mediaSources = []
    vi.stubGlobal('MediaSource', FakeMediaSource)
    vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:video')
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    vi.spyOn(console, 'info').mockImplementation(() => {})
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('buffers the stream with the codec its init segment names', async () => {
    await streamed(initSegment(hevc))
    expect(buffer?.type).toBe('video/mp4; codecs="hvc1.1.6.L93.B0"')
    expect(buffer?.end).toBe(1)
  })

  it('keeps ten seconds of played video from a heavy live stream', async () => {
    const { element, send } = await streamed(initSegment(hevc))
    Object.defineProperty(element, 'currentTime', { value: 100 })
    await send(3, 10_000_000)
    expect(buffer?.removed).toEqual([[0, 90]])
  })

  it('keeps five minutes of played video from a light live stream', async () => {
    const { element, send } = await streamed(initSegment(hevc))
    Object.defineProperty(element, 'currentTime', { value: 400 })
    await send(3)
    expect(buffer?.removed).toEqual([[0, 100]])
  })

  it('keeps recently played live video', async () => {
    const { element, send } = await streamed(initSegment(hevc))
    Object.defineProperty(element, 'currentTime', { value: 5 })
    await send(2)
    expect(buffer?.removed).toEqual([])
  })

  it('keeps all of a recording, to seek over', async () => {
    const { element, send, load } = await streamed(initSegment(hevc))
    await load(60)
    Object.defineProperty(element, 'currentTime', { value: 100 })
    await send(2)
    expect(buffer?.removed).toEqual([])
  })

  it('ends a recording that has finished downloading instead of reconnecting', async () => {
    const { load, close } = await streamed(initSegment(hevc))
    await load(60)
    await close()

    expect(mediaSources[0]?.endOfStream).toHaveBeenCalled()
    expect(console.warn).not.toHaveBeenCalled()
  })

  it('counts a live stream that ends as lost', async () => {
    const { load, close } = await streamed(initSegment(hevc))
    await load(Infinity)
    await close()

    expect(mediaSources[0]?.endOfStream).not.toHaveBeenCalled()
    expect(console.warn).toHaveBeenCalledWith(
      expect.stringContaining('The video stream ended.'),
      expect.anything(),
    )
  })

  // Chromium reloads a source left on the element, which a used `MediaSource` fails as a format
  // error, so a reconnect must not hold on to the lost one while its request is answered.
  it('lets go of a lost stream while reconnecting', async () => {
    const { element, load, close } = await streamed(initSegment(hevc))
    await load(Infinity)
    expect(element.getAttribute('src')).toBe('blob:video')

    await close()
    expect(element.hasAttribute('src')).toBe(false)
  })

  it('jumps a live picture that has fallen behind back to the newest frame', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
    const { element, load } = await streamed(initSegment(hevc))
    await load(Infinity)
    playing(element, 10, 20)

    vi.advanceTimersByTime(1000)
    expect(element.currentTime).toBe(19.5)
  })

  it.each([
    [18.95, 1.1],
    [18, 1.6],
    [15.5, 2.8],
  ])('plays a live picture behind at %s fast, faster the further behind', async (at, rate) => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
    const { element, load } = await streamed(initSegment(hevc))
    await load(Infinity)
    playing(element, at, 20)

    vi.advanceTimersByTime(1000)
    expect(element.currentTime).toBe(at)
    expect(element.playbackRate).toBe(rate)
  })

  it('eases a catch-up down to its slowest as the lag closes, then stops', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
    const { element, load } = await streamed(initSegment(hevc))
    await load(Infinity)
    playing(element, 17.5, 20)
    vi.advanceTimersByTime(250)
    expect(element.playbackRate).toBeGreaterThan(1.5)

    element.currentTime = 19.3
    vi.advanceTimersByTime(250)
    expect(element.playbackRate).toBe(1.1)

    element.currentTime = 19.6
    vi.advanceTimersByTime(250)
    expect(element.playbackRate).toBe(1)
  })

  it('plays a paused live picture on from where it was paused, at its own pace', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
    const { video, element, load } = await streamed(initSegment(hevc))
    await load(Infinity)
    await video.find('video').trigger('pause')
    playing(element, 10, 20)

    vi.advanceTimersByTime(1000)
    await settle()
    expect(element.currentTime).toBe(10)
    expect(element.playbackRate).toBe(1)
    expect(status(video)?.live).toBe('behind')

    status(video)?.goLive?.()
    expect(element.currentTime).toBe(19.5)
  })

  it('leaves a recording at its own pace', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
    const { element, load } = await streamed(initSegment(hevc))
    await load(60)
    playing(element, 10, 20)

    vi.advanceTimersByTime(1000)
    expect(element.currentTime).toBe(10)
    expect(element.playbackRate).toBe(1)
  })

  it('marks live video live in the header', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
    const { video, element, load } = await streamed(initSegment(hevc))
    await load(Infinity)
    playing(element, 19.8, 20)

    vi.advanceTimersByTime(1000)
    await settle()
    expect(status(video)).toMatchObject({ text: 'HTTP (Auto)', live: 'live' })
  })

  it('grays the live mark behind the newest frame, and goes back to live on demand', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
    const { video, element, load } = await streamed(initSegment(hevc))
    await load(Infinity)
    playing(element, 18, 20)

    vi.advanceTimersByTime(1000)
    await settle()
    expect(status(video)?.live).toBe('behind')

    status(video)?.goLive?.()
    expect(element.currentTime).toBe(19.5)
  })

  it('never marks a recording live', async () => {
    const { video, load } = await streamed(initSegment(hevc))
    await load(60)
    expect(status(video)).toMatchObject({ text: 'HTTP (Auto)' })
    expect(status(video)?.live).toBeUndefined()
  })

  it('cycles the transport setting from the header on a click', async () => {
    const { video } = await streamed(initSegment(hevc))
    status(video)?.cycle?.()
    await settle()
    expect(video.props('widget').transport).toBe('webrtc')
    // Still named while it cannot settle, rather than leaving the header blank.
    expect(status(video)?.text).toBe('WebRTC')
  })

  it('plays a codec the browser cannot buffer straight from its URL', async () => {
    isTypeSupported = () => false
    const { video } = await streamed(initSegment(hevc))

    expect(buffer).toBeNull()
    expect(video.find('video').attributes('src')).toContain('/queries/video')
  })

  it('names the codec the browser cannot play once its URL fails too, without reconnecting', async () => {
    isTypeSupported = () => false
    const { video, error } = await streamed(initSegment(hevc))
    await error(MediaError.MEDIA_ERR_SRC_NOT_SUPPORTED)

    expect(console.warn).toHaveBeenCalledWith(
      expect.stringContaining('This browser cannot play H.265 (HEVC) video.'),
    )
    expect(video.find('[data-video-error]').exists()).toBe(true)
    expect(video.find('video').attributes('src')).not.toContain('attempt=')
  })

  it('plays a plain MP4 straight from its URL', async () => {
    const { video } = await streamed(plainInitSegment(hevc))

    expect(buffer).toBeNull()
    expect(video.find('video').attributes('src')).toContain('/queries/video')
  })

  it('plays a stream the buffer refuses straight from its URL', async () => {
    const { video, error } = await streamed(initSegment(hevc))
    await error(MediaError.MEDIA_ERR_SRC_NOT_SUPPORTED)

    expect(video.find('video').attributes('src')).toContain('/queries/video')
  })

  it('reconnects a stream that fails to decode, buffering it again', async () => {
    const { video, error } = await streamed(initSegment(hevc))
    await error(MediaError.MEDIA_ERR_DECODE)

    expect(console.warn).toHaveBeenCalledWith(
      expect.stringContaining('The video element reported an error.'),
      expect.anything(),
    )
    expect(video.find('video').attributes('src')).toBeUndefined()
  })
})
