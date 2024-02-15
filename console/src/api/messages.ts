import { Address } from '@/address'
import {
  BaseFailModel,
  DateTimeModel,
  ItemStreamFilter,
  UseStreamOptions,
  createQueryParams,
  createResultType,
  get,
  getWebSocketURI,
  post,
  useStream,
} from '@/api/shared'
import { defineStore } from 'pinia'
import { MaybeRef, computed, isRef } from 'vue'
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

export async function getMessages(params: {
  address?: Address
  search?: string
  within?: number
  after?: string
  before?: string
  limit?: number
  order?: 'new-to-old' | 'old-to-new'
}): Promise<Message[]> {
  return await get(`/api/messages${createQueryParams(params)}`, Zod.array(MessageModel))
}

export function useMessageStream(
  filter: MaybeRef<ItemStreamFilter>,
  onReceive: (message: Message, params: ItemStreamFilter) => unknown,
  options?: MaybeRef<UseStreamOptions>
) {
  useStream(
    computed(() =>
      getWebSocketURI(`/api/messages${createQueryParams(isRef(filter) ? filter.value : filter)}`)
    ),
    filter,
    // eslint-disable-next-line @typescript-eslint/ban-ts-comment
    // @ts-ignore
    MessageModel,
    onReceive,
    options
  )
}

export type SendMessageResult = Zod.infer<typeof SendMessageResultModel>
const SendMessageResultModel = createResultType(MessageModel, BaseFailModel)

export async function sendMessage(address: Address, data: string): Promise<SendMessageResult> {
  return await post(
    `/api/components/${address}/procedures/send-message/call`,
    SendMessageResultModel,
    { data }
  )
}

export const useMessages = defineStore('messages', () => {
  return {
    getAll: getMessages,
    useStream: useMessageStream,
    send: sendMessage,
  }
})
