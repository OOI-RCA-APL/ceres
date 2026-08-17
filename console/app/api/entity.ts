import * as z from 'zod'

import { AddressModel, AddressSelectorModel } from '@/api/address'
import { DateTimeModel } from '@/api/shared'

export type Entity = z.infer<typeof EntityModel>
export const EntityModel = z.object({})

export type EntityFilter = z.infer<typeof EntityFilterModel>
export const EntityFilterModel = z.object({
  limit: z.number().nullish(),
  offset: z.number().nullish(),
})

export type FilterOperators<T> = T & {
  and?: T | T[] | null
  or?: T | T[] | null
}

export type UUIDEntity = z.infer<typeof UUIDEntityModel>
export const UUIDEntityModel = z.object({
  id: z.string(),
})

export type UUIDEntityFilter = z.infer<typeof UUIDEntityFilterModel>
export const UUIDEntityFilterModel = EntityFilterModel.extend({
  id: z.string().nullish(),
}).partial()

export type Item = z.infer<typeof ItemModel>
export const ItemModel = z.object({
  address: AddressModel,
})

export type ItemFilter = z.infer<typeof ItemFilterModel>
export const ItemFilterModel = EntityFilterModel.extend({
  address: AddressSelectorModel.nullish(),
}).partial()

export type Record = z.infer<typeof RecordModel>
export const RecordModel = UUIDEntityModel.extend(ItemModel.shape).extend({
  timestamp: DateTimeModel,
})

export type RecordOrder = z.infer<typeof RecordOrderModel>
export const RecordOrderModel = z.enum(['timestamp', 'timestamp:asc', 'timestamp:desc'])

export type RecordFilter = z.infer<typeof RecordFilterModel>
export const RecordFilterModel = UUIDEntityFilterModel.extend(ItemFilterModel.shape).extend({
  after: z.string().nullish(),
  before: z.string().nullish(),
  timespan: z.union([z.number(), z.string()]).nullish(),
  min_age: z.union([z.number(), z.string()]).nullish(),
  max_age: z.union([z.number(), z.string()]).nullish(),
  subsample_every: z.union([z.number(), z.string()]).nullish(),
  subsample: z.number().nullish(),
  subsample_select: z.enum(['first', 'last']).nullish(),
  after_hour: z.number().nullish(),
  before_hour: z.number().nullish(),
  after_minute: z.number().nullish(),
  before_minute: z.number().nullish(),
  order: RecordOrderModel.nullish(),
})
