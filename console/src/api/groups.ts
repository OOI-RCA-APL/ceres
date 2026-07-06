import { defineStore } from 'pinia'
import Zod from 'zod'

import { useClient } from '@/api/client'
import { UUIDEntityModel } from '@/api/entity'

export type Group = Zod.infer<typeof GroupModel>
export const GroupModel = UUIDEntityModel.extend({
  name: Zod.string(),
  description: Zod.string(),
})

export type GroupMembership = Zod.infer<typeof GroupMembershipModel>
export const GroupMembershipModel = Zod.object({
  user_id: Zod.string(),
  group_id: Zod.string(),
})

export const useGroups = defineStore('groups', () => {
  const client = useClient()

  async function get(id: string): Promise<Group | null> {
    try {
      return await client.get(`/api/groups/${id}`, {
        parse: GroupModel,
      })
    } catch {
      return null
    }
  }

  async function getAll(): Promise<Group[]> {
    return await client.get('/api/groups', {
      parse: Zod.array(GroupModel),
    })
  }

  async function create(data: { name: string; description?: string }): Promise<Group> {
    return await client.post('/api/groups', {
      data,
      parse: GroupModel,
    })
  }

  async function update(id: string, data: Partial<{ name: string; description: string }>) {
    return await client.patch(`/api/groups/${id}`, {
      data,
    })
  }

  async function del(id: string) {
    return await client.delete(`/api/groups/${id}`)
  }

  async function getMembers(id: string): Promise<GroupMembership[]> {
    return await client.get(`/api/groups/${id}/members`, {
      parse: Zod.array(GroupMembershipModel),
    })
  }

  async function addMember(groupId: string, userId: string): Promise<GroupMembership> {
    return await client.post(`/api/groups/${groupId}/members`, {
      data: { user_id: userId, group_id: groupId },
      parse: GroupMembershipModel,
    })
  }

  async function removeMember(groupId: string, userId: string) {
    return await client.delete(`/api/groups/${groupId}/members/${userId}`)
  }

  return {
    get,
    getAll,
    create,
    update,
    delete: del,
    getMembers,
    addMember,
    removeMember,
  }
})
