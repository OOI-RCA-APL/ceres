import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'

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

vi.mock('@/environment', () => ({ isSafari: false, isMediaSourceSupported: true }))

function render(reconnect: boolean) {
  const widget = VideoWidgetModel.parse({
    id: 'video',
    type: 'video',
    query: '@camera::queries::video',
    reconnect,
  })
  return mount(CWorkspaceWidgetVideo, {
    props: { widget },
    global: { stubs: { 'c-text': true, 'c-button': true, 'c-tooltip': true, 'c-icon': true } },
  })
}

describe('c-workspace-widget-video', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.spyOn(console, 'warn').mockImplementation(() => {})
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('shows the error box on a lost stream when not reconnecting', async () => {
    const video = render(false)
    await video.find('video').trigger('error')

    expect(video.text()).toBe('')
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
})
