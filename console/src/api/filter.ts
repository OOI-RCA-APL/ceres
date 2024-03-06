import { Address } from '@/api/address'
import { MessageDirection } from '@/api/messages'
import { Level } from '@/api/shared'
import { UserRole } from '@/api/users'

export type DatabaseFilter = Partial<{
  search: string | null
  search_field: string | string[]
  id: string | null
  limit: number | null
  offset: number | null
}>

export type UserOrder = 'username' | 'email'

export type UserFilter = DatabaseFilter &
  Partial<{
    username: string | string[] | null
    email: string | string[] | null
    role: UserRole | UserRole[] | null
    disabled: boolean | null
    order: 'username' | 'email'
  }>

export type ItemOrder = 'new-to-old' | 'old-to-new'

export type ItemFilter = DatabaseFilter &
  Partial<{
    address: Address | null
    after: string | null
    before: string | null
    order: ItemOrder
  }>

export type MessageFilter = ItemFilter &
  Partial<{
    direction: MessageDirection | null
    content_contains: string | null
    content_prefix: string | null
    content_suffix: string | null
  }>

export type AlertFilter = ItemFilter &
  Partial<{
    level: Level | Level[] | null
    code_contains: string | null
    code_prefix: string | null
    code_suffix: string | null
  }>

export type LogEntryFilter = ItemFilter &
  Partial<{
    level: Level | Level[] | null
    content_contains: string | null
    content_prefix: string | null
    content_suffix: string | null
  }>
