import { AddressSelector } from '@/api/address'
import { DateTimeModel } from '@/api/shared'
import Zod from 'zod'

export type Entity = Zod.infer<typeof EntityModel>
export const EntityModel = Zod.object({})

export type EntityFilter = Partial<{
  search: string | null
  search_field: string | string[]
  limit: number | null
  offset: number | null
}>

export type UUIDEntity = Zod.infer<typeof UUIDEntityModel>
export const UUIDEntityModel = Zod.object({
  id: Zod.string(),
})

export type UUIDEntityFilter = EntityFilter & Partial<{ id: string | null }>

export type Item = Zod.infer<typeof ItemModel>
export const ItemModel = Zod.object({
  address: Zod.string().transform(AddressSelector.parse),
})

export type ItemFilter = EntityFilter & Partial<{ address: AddressSelector | null }>

export type Record = Zod.infer<typeof RecordModel>
export const RecordModel = UUIDEntityModel.merge(ItemModel).extend({
  timestamp: DateTimeModel,
})

export type RecordFilter = UUIDEntityFilter &
  ItemFilter &
  Partial<{
    after: string | null
    before: string | null
    order: 'timestamp' | '-timestamp' | null
  }>
