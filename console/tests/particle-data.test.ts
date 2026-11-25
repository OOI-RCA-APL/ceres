import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import { defineComponent, h, ref } from 'vue'

import { ParticleModel } from '@/api/particles'
import type { Particle } from '@/api/particles'
import { useLatestParticle } from '@/particle-data'
import type { ParticleSource } from '@/particle-data'

/** Fetches by address, each answered when its test resolves it. */
const fetches = vi.hoisted(() => new Map<string, (particles: unknown[]) => void>())
vi.mock('@/api/engine', () => ({
  useEngine: () => ({
    particles: {
      getAll: (query: { address: { toString(): string } }) =>
        new Promise((resolve) => fetches.set(query.address.toString(), resolve)),
    },
  }),
}))
/** Hands a record to the latest mounted reader's stream. */
const streamed = vi.hoisted(() => ({ receive: (_particle: Particle) => {} }))
vi.mock('@/api/client', () => ({
  useClient: () => ({
    useStream: (options: { onReceive: (particle: Particle) => void }) => {
      streamed.receive = options.onReceive
    },
  }),
}))

function particle(address: string, timestamp: string, connection: string | null = null): Particle {
  return ParticleModel.parse({
    id: address,
    address,
    timestamp,
    type: 'reading',
    connection,
    data: {},
  })
}

/** Mounts a reader of `source`, returning what it shows. */
function reading(source: ReturnType<typeof ref<ParticleSource>>) {
  let shown = (): Particle | null => null
  let connections = (): (string | null)[] => []
  mount(
    defineComponent({
      setup() {
        const latest = useLatestParticle(() => source.value ?? null)
        shown = () => latest.particle.value
        connections = () => latest.connections.value
        return () => h('div')
      },
    }),
  )

  return Object.assign(() => shown(), { connections: () => connections() })
}

describe('useLatestParticle', () => {
  it('drops a fetch for a source it has since left', async () => {
    const source = ref<ParticleSource>({ address: '@one', type: 'reading', connection: null })
    const shown = reading(source)
    await flushPromises()

    source.value = { address: '@two', type: 'reading', connection: null }
    await flushPromises()
    // The old source's answer is newer, so only its generation keeps it out.
    fetches.get('@two')?.([particle('@two', '2026-01-01T00:00:00Z')])
    fetches.get('@one')?.([particle('@one', '2026-01-02T00:00:00Z')])
    await flushPromises()

    expect(shown()?.address.toString()).toBe('@two')
  })

  it('learns the connection of a record older than the one it shows', async () => {
    const source = ref<ParticleSource>({ address: '@one', type: 'reading', connection: null })
    const shown = reading(source)
    await flushPromises()
    fetches.get('@one')?.([particle('@one', '2026-01-02T00:00:00Z', 'a')])
    await flushPromises()

    streamed.receive(particle('@one', '2026-01-01T00:00:00Z', 'b'))
    streamed.receive(particle('@one', '2026-01-01T00:00:00Z'))

    expect(shown()?.connection).toBe('a')
    expect(shown.connections()).toEqual(['a', 'b', null])
  })
})
