import { DeepMaybeRef } from '@vueuse/core'
import { defineStore } from 'pinia'
import { MaybeRef } from 'vue'
import Zod from 'zod'

import { StreamOptions, useClient } from '@/api/client'
import { RecordFilterModel, RecordModel } from '@/api/entity'
import { dataloader } from '@/utilities'

export type Particle = Zod.infer<typeof ParticleModel>
export const ParticleModel = RecordModel.extend({
  type: Zod.string(),
  data: Zod.record(Zod.unknown()),
}).readonly()

export type ParticleFilter = Zod.infer<typeof ParticleFilterModel>
export const ParticleFilterModel = RecordFilterModel.extend({
  type: Zod.string().nullish(),
  type_contains: Zod.string().nullish(),
  type_prefix: Zod.string().nullish(),
  type_suffix: Zod.string().nullish(),
})

export const useParticles = defineStore('particles', () => {
  const client = useClient()
  async function getAll(filter: ParticleFilter): Promise<Particle[]> {
    return (
      await client.get('/api/particles', {
        query: filter,
      })
    ).map(Object.freeze)
  }

  function useStream(
    filter: MaybeRef<ParticleFilter>,
    onReceive: (current: Particle) => unknown,
    options?: DeepMaybeRef<StreamOptions>
  ) {
    client.useStream({
      stream: {
        path: '/api/particles',
        query: filter,
      },
      parse: ParticleModel as any,
      onReceive,
      ...options,
    })
  }

  return {
    getAll: dataloader<typeof getAll, Particle[]>(getAll),
    useStream,
  }
})
