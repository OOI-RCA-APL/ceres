import { defineStore } from 'pinia'
import * as z from 'zod'

import { RecordFilterModel, RecordModel } from '@/api/entity'
import { recordEndpoint } from '@/api/records'
import { LevelModel } from '@/api/shared'

export type LogEntry = z.infer<typeof LogEntryModel>
export const LogEntryModel = RecordModel.extend({
  level: LevelModel,
  content: z.string(),
}).readonly()

export type LogEntryFilter = z.infer<typeof LogEntryFilterModel>
export const LogEntryFilterModel = RecordFilterModel.extend({
  level: z.union([LevelModel, z.array(LevelModel)]).nullish(),
  min_level: LevelModel.nullish(),
  max_level: LevelModel.nullish(),
  contains: z.string().nullish(),
  prefix: z.string().nullish(),
  suffix: z.string().nullish(),
})

export const useLogs = defineStore('logs', () => {
  return recordEndpoint<LogEntry, LogEntryFilter>('/api/logs', LogEntryModel)
})
