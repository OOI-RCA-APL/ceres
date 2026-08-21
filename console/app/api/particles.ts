import { defineStore } from 'pinia'
import * as z from 'zod'

import { RecordFilterModel, RecordModel } from '@/api/entity'
import { recordEndpoint } from '@/api/records'

export type Particle = z.infer<typeof ParticleModel>
export const ParticleModel = RecordModel.extend({
  // Omitted rather than null for a particle no connection produced, so a default is needed.
  connection: z.string().nullish().default(null),
  type: z.string(),
  data: z.record(z.string(), z.unknown()),
}).readonly()

export type ParticleFilter = z.infer<typeof ParticleFilterModel>
export const ParticleFilterModel = RecordFilterModel.extend({
  connection: z.string().nullish(),
  connection_contains: z.string().nullish(),
  type: z.string().nullish(),
  type_contains: z.string().nullish(),
  type_prefix: z.string().nullish(),
  type_suffix: z.string().nullish(),
  data_contains: z.string().nullish(),
  data_prefix: z.string().nullish(),
  data_suffix: z.string().nullish(),
})

export const useParticles = defineStore('particles', () => {
  return recordEndpoint<Particle, ParticleFilter>('/api/particles', ParticleModel)
})
