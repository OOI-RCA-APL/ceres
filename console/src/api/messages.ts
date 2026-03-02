import { DeepMaybeRef } from '@vueuse/core'
import { defineStore } from 'pinia'
import { MaybeRef } from 'vue'
import Zod from 'zod'

import { Address } from '@/api/address'
import { useClient, StreamOptions } from '@/api/client'
import { RecordFilterModel, RecordModel } from '@/api/entity'
import { ResultModel } from '@/api/shared'
import { Failure } from '@/errors'
import { dataloader } from '@/utilities'

export type MessageDirection = Zod.infer<typeof MessageDirectionModel>
export const MessageDirectionModel = Zod.enum(['send', 'receive'])

export type Message = Zod.infer<typeof MessageModel>
export const MessageModel = RecordModel.extend({
  connection: Zod.string().nullable(),
  direction: MessageDirectionModel,
  data: Zod.string(),
}).readonly()

export type MessageFilter = Zod.infer<typeof MessageFilterModel>
export const MessageFilterModel = RecordFilterModel.extend({
  connection: Zod.string().nullish(),
  connection_contains: Zod.string().nullish(),
  direction: MessageDirectionModel.nullish(),
  contains: Zod.string().nullish(),
  prefix: Zod.string().nullish(),
  suffix: Zod.string().nullish(),
})

export type SendMessageResult = Zod.infer<typeof SendMessageResultModel>
const SendMessageResultModel = ResultModel(MessageModel)

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

  async function send(
    address: Address,
    connection: string,
    data: string
  ): Promise<Message | Failure> {
    return await client.post(`/api/components/${address}/connections/${connection}/send`, {
      data: { data },
    })
  }

  return {
    getAll: dataloader<typeof getAll, Message[]>(getAll),
    useStream,
    send,
  }
})
