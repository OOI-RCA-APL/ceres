import { DeepMaybeRef } from '@vueuse/core'
import moment, { Moment } from 'moment'
import { defineStore } from 'pinia'
import { MaybeRef } from 'vue'
import Zod from 'zod'

import { StreamOptions, useClient } from '@/api/client'
import { RecordFilterModel, RecordModel } from '@/api/entity'

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

  type PendingEntry = {
    timestamp: Moment
    promise: Promise<Particle[]>
  }

  const pending = new Map<string, PendingEntry>()

  async function getAll(filter: ParticleFilter): Promise<Particle[]> {
    const key = JSON.stringify(filter)
    const entry = pending.get(key)
    if (entry && entry.timestamp.isAfter(moment.utc().subtract(0.1, 'seconds'))) {
      return await entry.promise
    }

    try {
      const promise = client.get('/api/particles', {
        query: filter,
        parse: ParticleModel.array(),
      })
      pending.set(key, { timestamp: moment.utc(), promise })
      return await promise
    } finally {
      pending.delete(key)
    }
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
    getAll,
    useStream,
  }
})
