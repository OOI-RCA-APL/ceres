import Zod from 'zod'

import { AddressSelector } from '@/api/address'
import { DateTimeModel } from '@/api/shared'

export type Entity = Zod.infer<typeof EntityModel>
export const EntityModel = Zod.object({})

export type EntityFilter = Zod.infer<typeof EntityFilterModel>
export const EntityFilterModel = Zod.object({
  search: Zod.string().nullable(),
  search_field: Zod.union([Zod.string(), Zod.array(Zod.string())]).nullable(),
  limit: Zod.number().nullable(),
  offset: Zod.number().nullable(),
}).partial()

export type UUIDEntity = Zod.infer<typeof UUIDEntityModel>
export const UUIDEntityModel = Zod.object({
  id: Zod.string(),
})

export type UUIDEntityFilter = Zod.infer<typeof UUIDEntityFilterModel>
export const UUIDEntityFilterModel = EntityFilterModel.extend({
  id: Zod.string().nullable(),
}).partial()

export type Item = Zod.infer<typeof ItemModel>
export const ItemModel = Zod.object({
  address: Zod.string().transform(AddressSelector.parse),
})

export type ItemFilter = Zod.infer<typeof ItemFilterModel>
export const ItemFilterModel = EntityFilterModel.extend({
  address: Zod.string().transform(AddressSelector.parse).nullable(),
}).partial()

export type Record = Zod.infer<typeof RecordModel>
export const RecordModel = UUIDEntityModel.merge(ItemModel).extend({
  timestamp: DateTimeModel,
})

export type RecordOrder = Zod.infer<typeof RecordOrderModel>
export const RecordOrderModel = Zod.enum(['timestamp', '-timestamp'])

export type RecordFilter = Zod.infer<typeof RecordFilterModel>
export const RecordFilterModel = UUIDEntityFilterModel.merge(ItemFilterModel)
  .extend({
    after: Zod.string().nullable(),
    before: Zod.string().nullable(),
    order: RecordOrderModel.nullable(),
  })
  .partial()
