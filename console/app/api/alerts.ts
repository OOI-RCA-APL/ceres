import { defineStore } from 'pinia'
import * as z from 'zod'

import { RecordFilterModel, RecordModel } from '@/api/entity'
import { recordEndpoint } from '@/api/records'
import { LevelModel } from '@/api/shared'

export type Alert = z.infer<typeof AlertModel>
export const AlertModel = RecordModel.extend({
  level: LevelModel,
  type: z.string(),
  data: z.record(z.string(), z.unknown()).default(() => ({})),
}).readonly()

export type AlertFilter = z.infer<typeof AlertFilterModel>
export const AlertFilterModel = RecordFilterModel.extend({
  level: z.union([LevelModel, z.array(LevelModel)]).nullish(),
  min_level: LevelModel.nullish(),
  max_level: LevelModel.nullish(),
  type_contains: z.string().nullish(),
  type_prefix: z.string().nullish(),
  type_suffix: z.string().nullish(),
  data_contains: z.string().nullish(),
  data_prefix: z.string().nullish(),
  data_suffix: z.string().nullish(),
})

export const useAlerts = defineStore('alerts', () => {
  return recordEndpoint<Alert, AlertFilter>('/api/alerts', AlertModel)
})
