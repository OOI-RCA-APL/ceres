import { defineStore } from 'pinia'
import Zod from 'zod'

import { useClient } from '@/api/client'

export type PermissionTargetType = Zod.infer<typeof PermissionTargetTypeModel>
export const PermissionTargetTypeModel = Zod.enum(['component', 'tag', 'all'])

export type ComponentAccessLevel = Zod.infer<typeof ComponentAccessLevelModel>
export const ComponentAccessLevelModel = Zod.enum(['view', 'operate', 'manage'])

export type UserPermission = Zod.infer<typeof UserPermissionModel>
export const UserPermissionModel = Zod.object({
  user_id: Zod.string(),
  target_type: PermissionTargetTypeModel,
  target: Zod.string(),
  level: ComponentAccessLevelModel,
})

export type GroupPermission = Zod.infer<typeof GroupPermissionModel>
export const GroupPermissionModel = Zod.object({
  group_id: Zod.string(),
  target_type: PermissionTargetTypeModel,
  target: Zod.string(),
  level: ComponentAccessLevelModel,
})

export type EffectiveAccess = Zod.infer<typeof EffectiveAccessModel>
export const EffectiveAccessModel = Zod.object({
  level: ComponentAccessLevelModel.nullable(),
})

export type ComponentEffectiveAccess = Zod.infer<typeof ComponentEffectiveAccessModel>
export const ComponentEffectiveAccessModel = Zod.object({
  address: Zod.string(),
  level: ComponentAccessLevelModel,
})

export const usePermissions = defineStore('permissions', () => {
  const client = useClient()

  async function getUserPermissions(userId: string): Promise<UserPermission[]> {
    return await client.get(`/api/permissions/user/${userId}`, {
      parse: Zod.array(UserPermissionModel),
    })
  }

  async function getGroupPermissions(groupId: string): Promise<GroupPermission[]> {
    return await client.get(`/api/permissions/group/${groupId}`, {
      parse: Zod.array(GroupPermissionModel),
    })
  }

  async function setUserPermission(
    userId: string,
    data: { target_type: PermissionTargetType; target: string; level: ComponentAccessLevel }
  ): Promise<UserPermission> {
    return await client.put(`/api/permissions/user/${userId}`, {
      data,
      parse: UserPermissionModel,
    })
  }

  async function deleteUserPermission(
    userId: string,
    data: { target_type: PermissionTargetType; target: string }
  ) {
    return await client.delete(`/api/permissions/user/${userId}`, {
      data,
    })
  }

  async function setGroupPermission(
    groupId: string,
    data: { target_type: PermissionTargetType; target: string; level: ComponentAccessLevel }
  ): Promise<GroupPermission> {
    return await client.put(`/api/permissions/group/${groupId}`, {
      data,
      parse: GroupPermissionModel,
    })
  }

  async function deleteGroupPermission(
    groupId: string,
    data: { target_type: PermissionTargetType; target: string }
  ) {
    return await client.delete(`/api/permissions/group/${groupId}`, {
      data,
    })
  }

  async function getEffectiveAccess(userId: string, address: string): Promise<EffectiveAccess> {
    return await client.get(`/api/permissions/effective/${userId}/${address}`, {
      parse: EffectiveAccessModel,
    })
  }

  async function getAllEffectiveAccess(userId: string): Promise<ComponentEffectiveAccess[]> {
    return await client.get(`/api/permissions/effective/${userId}`, {
      parse: Zod.array(ComponentEffectiveAccessModel),
    })
  }

  return {
    getUserPermissions,
    getGroupPermissions,
    setUserPermission,
    deleteUserPermission,
    setGroupPermission,
    deleteGroupPermission,
    getEffectiveAccess,
    getAllEffectiveAccess,
  }
})
