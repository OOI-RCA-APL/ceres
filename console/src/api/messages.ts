import { defineStore } from 'pinia'
import { MaybeRef, computed, unref } from 'vue'
import Zod from 'zod'

import { Address } from '@/api/address'
import { StreamOptions, useClient } from '@/api/client'
import { RecordFilter, RecordModel } from '@/api/entity'
import { BaseFailModel, createResultType } from '@/api/shared'

export type MessageDirection = Zod.infer<typeof MessageDirectionModel>
export const MessageDirectionModel = Zod.enum(['send', 'receive'])

export type Message = Zod.infer<typeof MessageModel>
export const MessageModel = RecordModel.extend({
  direction: MessageDirectionModel,
  content: Zod.string(),
})

export type MessageFilter = RecordFilter &
  Partial<{
    direction: MessageDirection | null
    content_contains: string | null
    content_prefix: string | null
    content_suffix: string | null
  }>

export type SendMessageResult = Zod.infer<typeof SendMessageResultModel>
const SendMessageResultModel = createResultType(MessageModel, BaseFailModel)

export const useMessages = defineStore('messages', () => {
  const client = useClient()

  async function getAll(filter: MessageFilter): Promise<Message[]> {
    return await client.get('/api/messages', {
      query: filter,
      parse: Zod.array(MessageModel),
    })
  }

  function useStream(
    filter: MaybeRef<MessageFilter>,
    onReceive: (current: Message) => unknown,
    options?: MaybeRef<Omit<StreamOptions, 'query'>>
  ) {
    client.useStream(
      '/api/messages',
      MessageModel,
      onReceive,
      computed(() => ({
        query: filter,
        ...unref(options),
      }))
    )
  }

  async function send(address: Address, data: string): Promise<SendMessageResult> {
    return await client.post(`/api/components/${address}/procedures/send/call`, {
      data: { data },
      parse: SendMessageResultModel,
    })
  }
  return {
    getAll,
    useStream,
    send,
  }
})
