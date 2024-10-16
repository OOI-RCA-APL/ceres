import { defineStore } from 'pinia'
import { MaybeRef, computed, unref } from 'vue'
import Zod from 'zod'

import { StreamOptions, useClient } from '@/api/client'
import { RecordFilterModel, RecordModel } from '@/api/entity'

export type Particle = Zod.infer<typeof ParticleModel>
export const ParticleModel = RecordModel.extend({
  type: Zod.string(),
  data: Zod.record(Zod.unknown()),
})

export type ParticleFilter = Zod.infer<typeof ParticleFilterModel>
export const ParticleFilterModel = RecordFilterModel.extend({
  type: Zod.string().nullable(),
  type_contains: Zod.string().nullable(),
  type_prefix: Zod.string().nullable(),
  type_suffix: Zod.string().nullable(),
}).partial()

export const useParticles = defineStore('particles', () => {
  const client = useClient()

  async function getAll(filter: ParticleFilter): Promise<Particle[]> {
    return await client.get('/api/particles', {
      query: filter,
      parse: Zod.array(ParticleModel),
    })
  }

  function useStream(
    filter: MaybeRef<ParticleFilter>,
    onReceive: (current: Particle) => unknown,
    options?: MaybeRef<Omit<StreamOptions, 'query'>>
  ) {
    client.useStream(
      '/api/particles',
      ParticleModel,
      onReceive,
      computed(() => ({
        query: filter,
        ...unref(options),
      }))
    )
  }

  return {
    getAll,
    useStream,
  }
})
