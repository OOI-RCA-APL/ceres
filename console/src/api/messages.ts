import { DeepMaybeRef } from '@vueuse/core'
import { defineStore } from 'pinia'
import { MaybeRef } from 'vue'
import Zod from 'zod'

import { Address } from '@/api/address'
import { useClient, StreamOptions } from '@/api/client'
import { RecordFilterModel, RecordModel } from '@/api/entity'
import { BaseFailModel, createResultType } from '@/api/shared'
import { dataloader } from '@/utilities'

export type MessageDirection = Zod.infer<typeof MessageDirectionModel>
export const MessageDirectionModel = Zod.enum(['send', 'receive'])

export type Message = Zod.infer<typeof MessageModel>
export const MessageModel = RecordModel.extend({
  direction: MessageDirectionModel,
  content: Zod.string(),
}).readonly()

export type MessageFilter = Zod.infer<typeof MessageFilterModel>
export const MessageFilterModel = RecordFilterModel.extend({
  direction: MessageDirectionModel.nullish(),
  contains: Zod.string().nullish(),
  prefix: Zod.string().nullish(),
  suffix: Zod.string().nullish(),
})

export type SendMessageResult = Zod.infer<typeof SendMessageResultModel>
const SendMessageResultModel = createResultType(MessageModel, BaseFailModel)

export const useMessages = defineStore('messages', () => {
  const client = useClient()

  async function getAll(filter: MessageFilter): Promise<Message[]> {
    return (
      await client.get('/api/messages', {
        query: filter,
      })
    ).map(Object.freeze)
  }

  function useStream(
    filter: MaybeRef<MessageFilter>,
    onReceive: (current: Message) => unknown,
    options?: DeepMaybeRef<StreamOptions>
  ) {
    client.useStream({
      stream: {
        path: '/api/messages',
        query: filter,
      },
      parse: MessageModel,
      onReceive,
      ...options,
    })
  }

  async function send(address: Address, data: string): Promise<SendMessageResult> {
    return await client.post(`/api/components/${address}/procedures/send/call`, {
      data: { data },
      parse: SendMessageResultModel,
    })
  }

  return {
    getAll: dataloader<typeof getAll, Message[]>(getAll),
    useStream,
    send,
  }
})
