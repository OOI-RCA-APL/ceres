import { defineStore } from 'pinia'
import * as z from 'zod'

import type { Address } from '@/api/address'
import { useClient } from '@/api/client'
import { RecordFilterModel, RecordModel } from '@/api/entity'
import { recordEndpoint } from '@/api/records'
import type { Result } from '@/api/shared'
import type { Failure } from '@/errors'

export type MessageDirection = z.infer<typeof MessageDirectionModel>
export const MessageDirectionModel = z.enum(['send', 'receive'])

export type Message = z.infer<typeof MessageModel>
export const MessageModel = RecordModel.extend({
  connection: z.string().nullable(),
  direction: MessageDirectionModel,
  data: z.string(),
}).readonly()

export type MessageFilter = z.infer<typeof MessageFilterModel>
export const MessageFilterModel = RecordFilterModel.extend({
  connection: z.string().nullish(),
  connection_contains: z.string().nullish(),
  direction: MessageDirectionModel.nullish(),
  contains: z.string().nullish(),
  prefix: z.string().nullish(),
  suffix: z.string().nullish(),
})

export type SendMessageResult = Result<Message>

export const useMessages = defineStore('messages', () => {
  const client = useClient()

  async function send(
    address: Address,
    connection: string,
    data: string,
  ): Promise<Message | Failure> {
    return await client.post(`/api/components/${address}/connections/${connection}/send`, {
      data: { data },
    })
  }

  return {
    ...recordEndpoint<Message, MessageFilter>('/api/messages', MessageModel),
    send,
  }
})
