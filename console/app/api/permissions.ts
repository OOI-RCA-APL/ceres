import { defineStore } from 'pinia'
import * as z from 'zod'

import { useClient } from '@/api/client'

export type PermissionTargetType = z.infer<typeof PermissionTargetTypeModel>
export const PermissionTargetTypeModel = z.enum(['component', 'tag', 'all'])

export type ComponentAccessLevel = z.infer<typeof ComponentAccessLevelModel>
export const ComponentAccessLevelModel = z.enum(['view', 'operate', 'manage'])

export type UserPermission = z.infer<typeof UserPermissionModel>
export const UserPermissionModel = z.object({
  user_id: z.string(),
  target_type: PermissionTargetTypeModel,
  target: z.string(),
  level: ComponentAccessLevelModel,
})

export type GroupPermission = z.infer<typeof GroupPermissionModel>
export const GroupPermissionModel = z.object({
  group_id: z.string(),
  target_type: PermissionTargetTypeModel,
  target: z.string(),
  level: ComponentAccessLevelModel,
})

export type EffectiveAccess = z.infer<typeof EffectiveAccessModel>
export const EffectiveAccessModel = z.object({
  level: ComponentAccessLevelModel.nullable(),
})

export type AccessSource = z.infer<typeof AccessSourceModel>
export const AccessSourceModel = z.enum(['admin', 'default', 'component', 'tag', 'all'])

export type GrantOrigin = z.infer<typeof GrantOriginModel>
export const GrantOriginModel = z.enum(['user', 'group'])

export type ComponentEffectiveAccess = z.infer<typeof ComponentEffectiveAccessModel>
export const ComponentEffectiveAccessModel = z.object({
  address: z.string(),
  level: ComponentAccessLevelModel,
  source: AccessSourceModel,
  origin: GrantOriginModel.nullish(),
  group_id: z.string().nullish(),
})

export type PermissionTarget = {
  target_type: PermissionTargetType
  target: string
}

export type PermissionGrant = PermissionTarget & {
  level: ComponentAccessLevel
}

export const usePermissions = defineStore('permissions', () => {
  const client = useClient()

  async function getUserPermissions(userId: string): Promise<UserPermission[]> {
    return await client.get(`/api/permissions/user/${userId}`, {
      parse: z.array(UserPermissionModel),
    })
  }

  async function getGroupPermissions(groupId: string): Promise<GroupPermission[]> {
    return await client.get(`/api/permissions/group/${groupId}`, {
      parse: z.array(GroupPermissionModel),
    })
  }

  async function setUserPermission(userId: string, data: PermissionGrant): Promise<UserPermission> {
    return await client.put(`/api/permissions/user/${userId}`, {
      data,
      parse: UserPermissionModel,
    })
  }

  async function deleteUserPermission(userId: string, data: PermissionTarget) {
    return await client.delete(`/api/permissions/user/${userId}`, {
      data,
    })
  }

  async function setGroupPermission(
    groupId: string,
    data: PermissionGrant,
  ): Promise<GroupPermission> {
    return await client.put(`/api/permissions/group/${groupId}`, {
      data,
      parse: GroupPermissionModel,
    })
  }

  async function deleteGroupPermission(groupId: string, data: PermissionTarget) {
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
      parse: z.array(ComponentEffectiveAccessModel),
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
