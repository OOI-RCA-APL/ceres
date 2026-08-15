import { defineStore } from 'pinia'
import * as z from 'zod'

import { useClient } from '@/api/client'
import { type EntityFilter, type FilterOperators, UUIDEntityModel } from '@/api/entity'

export type User = z.infer<typeof UserModel>
export const UserModel = UUIDEntityModel.extend({
  username: z.string(),
  email: z.string(),
  admin: z.boolean(),
  disabled: z.boolean(),
})

export type UserCreate = Omit<User, 'id'> & { password: string }

export type UserOrder = 'username' | 'username:desc' | 'email' | 'email:desc'

export type UserFilter = FilterOperators<
  EntityFilter &
    Partial<{
      username: string | string[] | null
      username_contains: string | string[] | null
      username_prefix: string | string[] | null
      username_suffix: string | string[] | null
      email: string | string[] | null
      email_contains: string | string[] | null
      email_prefix: string | string[] | null
      email_suffix: string | string[] | null
      admin: boolean | null
      disabled: boolean | null
      order: UserOrder | null
    }>
>

export const useUsers = defineStore('users', () => {
  const client = useClient()

  async function get(id: string): Promise<User | null> {
    try {
      return await client.get(`/api/users/${id}`, {
        parse: UserModel,
      })
    } catch {
      return null
    }
  }

  async function getAll(filter?: UserFilter): Promise<User[]> {
    return await client.get('/api/users', {
      query: filter,
      parse: z.array(UserModel),
    })
  }

  async function create(data: UserCreate): Promise<User> {
    return await client.post('/api/users', {
      data,
      parse: UserModel,
    })
  }

  async function update(id: string, data: Partial<User & { password: string }>): Promise<User> {
    return client.patch(`/api/users/${id}`, {
      data,
      parse: UserModel,
    })
  }

  async function del(id: string): Promise<User> {
    return await client.delete(`/api/users/${id}`, {
      parse: UserModel,
    })
  }

  return {
    get,
    getAll,
    create,
    delete: del,
    update,
  }
})
