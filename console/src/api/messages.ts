import { Address } from '@/address'
import { ItemStreamFilter, StreamOptions, useClient } from '@/api/client'
import { BaseFailModel, DateTimeModel, createResultType } from '@/api/shared'
import { defineStore } from 'pinia'
import { MaybeRef, computed, unref } from 'vue'
import Zod from 'zod'

export type MessageDirection = Zod.infer<typeof MessageDirectionModel>
export const MessageDirectionModel = Zod.enum(['send', 'receive'])

export type Message = Zod.infer<typeof MessageModel>
export const MessageModel = Zod.object({
  id: Zod.string(),
  address: Zod.string().transform(Address.parse),
  timestamp: DateTimeModel,
  direction: MessageDirectionModel,
  content: Zod.string(),
})

export type SendMessageResult = Zod.infer<typeof SendMessageResultModel>
const SendMessageResultModel = createResultType(MessageModel, BaseFailModel)

export const useMessages = defineStore('messages', () => {
  const client = useClient()

  async function getMessages(filter: {
    address?: Address
    search?: string
    within?: number
    after?: string
    before?: string
    limit?: number
    order?: 'new-to-old' | 'old-to-new'
  }): Promise<Message[]> {
    return await client.get('/api/messages', {
      query: filter,
      parse: Zod.array(MessageModel),
    })
  }

  function useStream(
    filter: MaybeRef<ItemStreamFilter>,
    onReceive: (current: Message) => unknown,
    options?: MaybeRef<StreamOptions>
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
    return await client.post(`/api/components/${address}/procedures/send-message/call`, {
      data: { data },
      parse: SendMessageResultModel,
    })
  }
  return {
    getAll: getMessages,
    useStream,
    send,
  }
})
