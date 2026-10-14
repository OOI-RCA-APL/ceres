import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import CWorkspaceWidgetVideo from '@/components/c-workspace-widget-video.vue'
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

vi.mock('@/environment', () => ({ isSafari: true, isMediaSourceSupported: true }))

/** A source buffer holding one second of video per appended chunk. */
class FakeSourceBuffer extends EventTarget {
  start = 0
  end = 0
  removed: [number, number][] = []

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

let buffer: FakeSourceBuffer

class FakeMediaSource extends EventTarget {
  static isTypeSupported = () => true

  addSourceBuffer() {
    return buffer
  }

  override addEventListener(...args: Parameters<EventTarget['addEventListener']>) {
    super.addEventListener(...args)
    if (args[0] === 'sourceopen') {
      queueMicrotask(() => this.dispatchEvent(new Event('sourceopen')))
    }
  }
}

/** Mount the widget on a stream of `chunks` chunks, playing at `currentTime`, and drain it. */
async function streamed(chunks: number, currentTime: number) {
  // Left open like a live stream, since one that ends counts as lost and the widget asks again.
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (let index = 0; index < chunks; index++) {
        controller.enqueue(new Uint8Array([index]))
      }
    },
  })
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response(body, { headers: { 'content-type': 'video/mp4' } })),
  )

  const widget = VideoWidgetModel.parse({
    id: 'video',
    type: 'video',
    query: '@camera::queries::video',
  })
  const video = mount(CWorkspaceWidgetVideo, {
    props: { widget },
    global: { stubs: { 'c-text': true, 'c-button': true, 'c-tooltip': true, 'c-icon': true } },
  })
  const element = video.find('video').element as HTMLVideoElement
  Object.defineProperty(element, 'currentTime', { value: currentTime })

  for (let index = 0; index < chunks * 4; index++) {
    await flushPromises()
  }
}

describe('c-workspace-widget-video on Safari', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    buffer = new FakeSourceBuffer()
    vi.stubGlobal('MediaSource', FakeMediaSource)
    vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:video')
    vi.spyOn(console, 'warn').mockImplementation(() => {})
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('drops video played more than half a minute ago', async () => {
    await streamed(3, 100)
    expect(buffer.removed).toEqual([[0, 70]])
    expect(buffer.end).toBe(3)
  })

  it('keeps recently played video', async () => {
    await streamed(3, 10)
    expect(buffer.removed).toEqual([])
    expect(buffer.end).toBe(3)
  })
})
