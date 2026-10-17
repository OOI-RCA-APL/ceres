import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'

import CWorkspaceWidgetVideo from '@/components/c-workspace-widget-video.vue'
import { WhepRefusal } from '@/whep'
import type { WidgetStatus } from '@/widget-status'
import { VideoWidgetModel } from '@/workspace/models'

// The query's output, a stream unless a test makes it a file.
const output = vi.hoisted(() => ({ type: 'streaming', media: 'video/mp4' }))
vi.mock('@/api/engine', () => ({
  useEngine: () => ({
    components: {
      get: () => ({ procedures: [{ name: 'video', type: 'query', output }] }),
    },
  }),
}))

vi.mock('@/workspace', () => ({
  useWorkspace: () => ({ resolveAddress: (raw: string) => raw }),
}))

// Without a `MediaSource` every video plays straight from its URL. The buffered path has its own
// tests, in `c-workspace-widget-video-buffer.test.ts`.
vi.mock('@/environment', () => ({ isMediaSourceSupported: false }))

const openWhep = vi.hoisted(() => vi.fn())
vi.mock('@/whep', async (original) => ({ ...(await original<object>()), openWhep }))

/** A browser with WebRTC, whose sessions open as `opens` says. */
function webrtc(opens: () => Promise<unknown>) {
  vi.stubGlobal('RTCPeerConnection', vi.fn())
  openWhep.mockImplementation(opens)
}

const decoding = (received: number, decoded: number, decoder: string | null) => () =>
  Promise.resolve({ received, decoded, decoder, freezes: 0, frozenSeconds: 0 })
const session = () =>
  Promise.resolve({ stream: null, decoding: decoding(0, 0, null), hold: () => {}, close: () => {} })
// A session whose frames keep arriving with none decoded, as in Chrome after its hardware decoder
// fails and it falls back to one that decodes nothing.
const deadDecoder = () =>
  Promise.resolve({
    stream: null,
    decoding: decoding(
      500,
      40,
      'NullVideoDecoder (fallback from: ExternalDecoder (VideoToolboxVideoDecoder))',
    ),
    hold: () => {},
    close: () => {},
  })
const refused = () => Promise.reject(new WhepRefusal(409, 'codec'))
const full = () => Promise.reject(new WhepRefusal(503, 'full'))

function render(reconnect: boolean, transport = 'auto', settings: object = {}) {
  const widget = VideoWidgetModel.parse({
    id: 'video',
    type: 'video',
    query: '@device::queries::video',
    reconnect,
    transport,
    ...settings,
  })
  return mount(CWorkspaceWidgetVideo, {
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
}

/** The status the widget last sent up for its header. */
function status(video: ReturnType<typeof render>) {
  return video.emitted<[WidgetStatus | null]>('status')?.at(-1)?.[0]
}

/** Plays the widget's video, as a viewer starting it does. The element's own frame count keeps
rising, so only the decoder's count can tell a stopped decoder. */
async function playing(video: ReturnType<typeof render>) {
  const element = video.find('video').element as HTMLVideoElement
  let frames = 0
  Object.defineProperty(element, 'paused', { value: false })
  Object.defineProperty(element, 'getVideoPlaybackQuality', {
    value: () => ({ totalVideoFrames: (frames += 1) }),
  })
  await video.find('video').trigger('play')
}

/** The transport label the widget last sent up for its header. */
function transport(video: ReturnType<typeof render>) {
  return status(video)?.text
}

describe('c-workspace-widget-video', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.useFakeTimers()
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    vi.spyOn(console, 'info').mockImplementation(() => {})
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
    openWhep.mockReset()
  })

  it('plays over HTTP in a browser without WebRTC', () => {
    const video = render(false)

    expect(transport(video)).toBe('HTTP (Auto)')
    expect(openWhep).not.toHaveBeenCalled()
  })

  it('plays over WebRTC when the session opens', async () => {
    webrtc(session)
    const video = render(false)
    await flushPromises()

    expect(transport(video)).toBe('WebRTC (Auto)')
    expect(video.find('video').attributes('src')).toBeUndefined()
    expect(openWhep.mock.calls[0]?.[0]).toContain('/api/components/@device/procedures/video/whep')
    expect(openWhep.mock.calls[0]?.[0]).not.toContain('reordered')
  })

  it('lets a video held to WebRTC drop the frames a video sends out of order', async () => {
    webrtc(session)
    render(false, 'webrtc')
    await flushPromises()

    expect(new URL(openWhep.mock.calls[0]?.[0]).searchParams.get('reordered')).toBe('drop')
  })

  it('falls back to HTTP once, remembering it for the next widget', async () => {
    webrtc(refused)
    const first = render(false)
    await flushPromises()

    expect(transport(first)).toBe('HTTP (Auto)')
    expect(first.find('video').attributes('src')).toContain('/queries/video/call')

    const second = render(false)
    await flushPromises()
    expect(transport(second)).toBe('HTTP (Auto)')
    expect(openWhep).toHaveBeenCalledTimes(1)
  })

  it('says why a video held to WebRTC cannot play in this browser, without reconnecting', async () => {
    webrtc(refused)
    const video = render(true, 'webrtc')
    await flushPromises()

    expect(console.warn).toHaveBeenCalledWith(
      expect.stringContaining("This browser cannot decode this video's codec over WebRTC."),
    )
    expect(video.find('[data-video-error]').exists()).toBe(true)
    await vi.advanceTimersByTimeAsync(30_000)
    expect(openWhep).toHaveBeenCalledTimes(1)
  })

  it('falls back to HTTP for one try when the engine is full', async () => {
    webrtc(full)
    const first = render(false)
    await flushPromises()
    expect(transport(first)).toBe('HTTP (Auto)')

    webrtc(session)
    const second = render(false)
    await flushPromises()
    expect(transport(second)).toBe('WebRTC (Auto)')
  })

  it('stays on WebRTC when a session that played is lost', async () => {
    webrtc(session)
    const video = render(true)
    await flushPromises()

    openWhep.mockImplementation(refused)
    const [, { onLost }] = openWhep.mock.calls[0] as [string, { onLost: (reason: string) => void }]
    onLost('The WebRTC connection is failed.')
    await flushPromises()

    expect(openWhep).toHaveBeenCalledTimes(2)
    expect(transport(video)).toBe('WebRTC (Auto)')
    expect(video.find('video').attributes('src')).toBeUndefined()
  })

  it('shows the error box on a lost stream when not reconnecting', async () => {
    const video = render(false)
    await video.find('video').trigger('error')

    expect(transport(video)).toBe('HTTP (Auto)')
    expect(video.find('c-text-stub').exists()).toBe(true)
    expect(video.find('video').attributes('src')).not.toContain('attempt=')
  })

  it('reloads the stream at once and then on a countdown when reconnecting', async () => {
    const video = render(true)
    await video.find('video').trigger('error')

    expect(video.find('c-text-stub').exists()).toBe(false)
    expect(video.find('video').attributes('src')).toContain('#attempt=1')

    // The new attempt fails as well, after the old connection's last word has settled.
    vi.advanceTimersByTime(2000)
    await video.find('video').trigger('ended')
    await nextTick()
    expect(video.text()).toContain('Reconnecting in 5')

    vi.advanceTimersByTime(5000)
    await nextTick()
    expect(video.find('video').attributes('src')).toContain('#attempt=2')

    // Frames flow again, so the badge goes.
    await video.find('video').trigger('loadeddata')
    expect(video.text()).not.toContain('Reconnecting')
  })

  it('never steers a stream played from its URL, which cannot tell live from recorded', () => {
    const element = render(false).find('video').element as HTMLVideoElement
    Object.defineProperty(element, 'paused', { value: false })
    Object.defineProperty(element, 'buffered', {
      value: { length: 1, start: () => 0, end: () => 20 },
    })
    Object.defineProperty(element, 'seekable', {
      value: { length: 1, start: () => 0, end: () => 20 },
    })
    element.currentTime = 10

    vi.advanceTimersByTime(1000)
    expect(element.currentTime).toBe(10)
    expect(element.playbackRate).toBe(1)
  })

  it('reconnects a WebRTC video whose decoder stopped, naming the decoder', async () => {
    webrtc(deadDecoder)
    const video = render(true)
    await flushPromises()
    await playing(video)

    await vi.advanceTimersByTimeAsync(11_000)
    expect(console.warn).toHaveBeenCalledWith(
      expect.stringContaining('WebRTC decoded 40 of the 500 frames it received, with Null'),
    )
    expect(openWhep).toHaveBeenCalledTimes(2)
    expect(transport(video)).toBe('WebRTC (Auto)')
  })

  it('plays over HTTP once WebRTC stops showing frames twice in a minute', async () => {
    webrtc(deadDecoder)
    const video = render(true)
    await flushPromises()
    await playing(video)

    await vi.advanceTimersByTimeAsync(40_000)
    expect(transport(video)).toBe('HTTP (Auto)')
    expect(status(video)).toMatchObject({ text: 'HTTP (Auto)' })
    expect(video.find('video').attributes('src')).toContain('/queries/video/call')
    expect(openWhep).toHaveBeenCalledTimes(2)
  })

  it('keeps a video held to WebRTC on WebRTC however often it stalls', async () => {
    webrtc(deadDecoder)
    const video = render(true, 'webrtc')
    await flushPromises()
    await playing(video)

    await vi.advanceTimersByTimeAsync(60_000)
    expect(openWhep.mock.calls.length).toBeGreaterThanOrEqual(3)
    expect(video.find('video').attributes('src')).toBeUndefined()
  })

  it('lets a file play to its end without reconnecting', async () => {
    output.type = 'file'
    try {
      const video = render(true)
      await video.find('video').trigger('ended')

      expect(video.find('video').attributes('src')).not.toContain('attempt=')
      expect(video.find('c-text-stub').exists()).toBe(false)
    } finally {
      output.type = 'streaming'
    }
  })
})
