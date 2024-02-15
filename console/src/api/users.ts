import { useClient } from '@/api/client'
import { defineStore } from 'pinia'
import Zod from 'zod'

export type UserRole = Zod.infer<typeof UserRoleModel>
export const UserRoleModel = Zod.enum(['viewer', 'operator', 'admin'])

export type User = Zod.infer<typeof UserModel>
export const UserModel = Zod.object({
  id: Zod.string(),
  username: Zod.string(),
  email: Zod.string(),
  role: UserRoleModel,
  disabled: Zod.boolean(),
})

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

  async function getAll(): Promise<User[]> {
    return await client.get(`/api/users`, {
      parse: Zod.array(UserModel),
    })
  }

  async function create(data: Omit<User, 'id'> & { password: string }): Promise<User> {
    return await client.post(`/api/users`, {
      data: data,
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
