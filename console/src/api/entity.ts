import Zod from 'zod'

import { AddressSelector } from '@/api/address'
import { DateTimeModel } from '@/api/shared'

export type Entity = Zod.infer<typeof EntityModel>
export const EntityModel = Zod.object({})

export type EntityFilter = Zod.infer<typeof EntityFilterModel>
export const EntityFilterModel = Zod.object({
  limit: Zod.number().nullish(),
  offset: Zod.number().nullish(),
})

export type UUIDEntity = Zod.infer<typeof UUIDEntityModel>
export const UUIDEntityModel = Zod.object({
  id: Zod.string(),
})

export type UUIDEntityFilter = Zod.infer<typeof UUIDEntityFilterModel>
export const UUIDEntityFilterModel = EntityFilterModel.extend({
  id: Zod.string().nullish(),
}).partial()

export type Item = Zod.infer<typeof ItemModel>
export const ItemModel = Zod.object({
  address: Zod.string().transform(AddressSelector.parse),
})

export type ItemFilter = Zod.infer<typeof ItemFilterModel>
export const ItemFilterModel = EntityFilterModel.extend({
  address: Zod.string().transform(AddressSelector.parse).nullish(),
}).partial()

export type Record = Zod.infer<typeof RecordModel>
export const RecordModel = UUIDEntityModel.merge(ItemModel).extend({
  timestamp: DateTimeModel,
})

export type RecordOrder = Zod.infer<typeof RecordOrderModel>
export const RecordOrderModel = Zod.enum(['timestamp', 'timestamp:asc', 'timestamp:desc'])

export type RecordFilter = Zod.infer<typeof RecordFilterModel>
export const RecordFilterModel = UUIDEntityFilterModel.merge(ItemFilterModel).extend({
  after: Zod.string().nullish(),
  before: Zod.string().nullish(),
  timespan: Zod.union([Zod.number(), Zod.string()]).nullish(),
  min_age: Zod.union([Zod.number(), Zod.string()]).nullish(),
  max_age: Zod.union([Zod.number(), Zod.string()]).nullish(),
  after_hour: Zod.number().nullish(),
  before_hour: Zod.number().nullish(),
  after_minute: Zod.number().nullish(),
  before_minute: Zod.number().nullish(),
  order: RecordOrderModel.nullish(),
})
