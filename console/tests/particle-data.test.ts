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
vi.mock('@/api/client', () => ({ useClient: () => ({ useStream: () => {} }) }))

function particle(address: string, timestamp: string): Particle {
  return ParticleModel.parse({ id: address, address, timestamp, type: 'reading', data: {} })
}

/** Mounts a reader of `source`, returning what it shows. */
function reading(source: ReturnType<typeof ref<ParticleSource>>) {
  let shown = (): Particle | null => null
  mount(
    defineComponent({
      setup() {
        const { particle: latest } = useLatestParticle(() => source.value ?? null)
        shown = () => latest.value
        return () => h('div')
      },
    }),
  )

  return () => shown()
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
})
