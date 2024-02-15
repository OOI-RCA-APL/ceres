import { ErrorInfo, deleteOrError, get, getOrNull, patchOrError, postOrError } from '@/api/shared'
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
  async function getUser(id: string): Promise<User | null> {
    return await getOrNull(`/api/users/${id}`, UserModel)
  }

  async function getUsers(): Promise<User[]> {
    return await get(`/api/users`, Zod.array(UserModel))
  }

  async function deleteUser(id: string): Promise<User | ErrorInfo> {
    return await deleteOrError(`/api/users/${id}`, UserModel)
  }

  async function updateUser(
    id: string,
    data: Partial<User & { password: string }>
  ): Promise<User | ErrorInfo> {
    return await patchOrError(`/api/users/${id}`, UserModel, data)
  }

  async function createUser(
    data: Omit<User, 'id'> & { password: string }
  ): Promise<User | ErrorInfo> {
    return await postOrError(`/api/users`, UserModel, data)
  }
  return {
    get: getUser,
    getAll: getUsers,
    create: createUser,
    delete: deleteUser,
    update: updateUser,
  }
})
