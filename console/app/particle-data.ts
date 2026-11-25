import { computed, toValue, watch } from 'vue'
import type { MaybeRefOrGetter } from 'vue'

import { AddressSelector } from '@/api/address'
import { useClient } from '@/api/client'
import { useEngine } from '@/api/engine'
import { ParticleModel } from '@/api/particles'
import type { Particle } from '@/api/particles'
import { utc } from '@/time'

/** Where a widget reads particles from: one component's type, narrowed to a connection or not.
`address` is the concrete address a selector resolved to, null while it resolves to none. */
export type ParticleSource = {
  address: string | null
  type: string | null
  connection: string | null
}

/** The query a source reads through, the same for its fetch and its stream. */
function queryOf(source: ParticleSource) {
  return { address: source.address, type: source.type, connection: source.connection }
}

/** Whether `particle` belongs to `source`, which a stream message from the source before a change
can fail. */
function belongsTo(particle: Particle, source: ParticleSource): boolean {
  return (
    (source.type == null || particle.type === source.type) &&
    (source.connection == null || particle.connection === source.connection)
  )
}

/** The newest particle `source` holds, fetched whenever the source changes and kept current from
its live stream.

Each change starts a new generation, so a fetch for an earlier source that answers late is
dropped rather than shown under the new one.
*/
export function useLatestParticle(source: MaybeRefOrGetter<ParticleSource | null>) {
  const client = useClient()
  const engine = useEngine()

  let particle = $ref<Particle | null>(null)
  let generation = 0

  const current = $computed(() => toValue(source))

  /** Take `candidate` when it is newer than what is shown. */
  function offer(candidate: Particle) {
    if (particle == null || utc(candidate.timestamp).isAfter(particle.timestamp)) {
      particle = candidate
    }
  }

  watch(
    () => (current == null ? null : JSON.stringify(queryOf(current))),
    async () => {
      const fetched = ++generation
      particle = null
      if (current?.address == null) {
        return
      }

      const latest = (
        await engine.particles.getAll({
          ...queryOf(current),
          address: new AddressSelector(current.address),
          order: 'timestamp:desc',
          limit: 1,
        })
      )?.[0]
      if (latest != null && fetched === generation) {
        offer(latest)
      }
    },
    { immediate: true },
  )

  client.useStream({
    stream: computed(() => ({
      path: '/api/particles',
      query: current == null ? {} : queryOf(current),
    })),
    disable: () => current?.address == null,
    parse: ParticleModel,
    onReceive: (received: Particle) => {
      if (current != null && belongsTo(received, current)) {
        offer(received)
      }
    },
  })

  return { particle: $$(particle) }
}
