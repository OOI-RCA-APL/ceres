import type { MaybeRef } from 'vue'
import type * as z from 'zod'

import { type StreamOptions, useClient } from '@/api/client'
import { dataloader } from '@/utilities'

/** Shared `getAll` and `useStream` for a record endpoint (alerts, logs, messages, particles).

Bulk fetches skip zod parsing and freeze rows instead, since parsing every row of a large result
costs more than it protects, while streamed rows are parsed one at a time.
*/
export function recordEndpoint<TRecord, TFilter>(path: string, model: z.ZodType<TRecord>) {
  const client = useClient()

  async function getAll(filter: TFilter): Promise<TRecord[]> {
    return (
      await client.get(path, {
        query: filter as Record<string, unknown>,
      })
    ).map(Object.freeze)
  }

  function useStream(
    filter: MaybeRef<TFilter>,
    onReceive: (current: TRecord) => unknown,
    options?: StreamOptions,
  ) {
    client.useStream({
      stream: {
        path,
        query: filter,
      },
      parse: model,
      onReceive,
      ...options,
    })
  }

  return {
    getAll: dataloader<typeof getAll, TRecord[]>(getAll),
    useStream,
  }
}
