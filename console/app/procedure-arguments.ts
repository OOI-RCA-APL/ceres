import type { Address } from '@/api/address'
import { readStored, writeStored } from '@/persistence'
import type { KeyInput } from '@/persistence'

/** Where the arguments last entered for one procedure of one component are stored.

Shared by every form that runs the procedure, so a button switched to it offers what the
procedures widget last sent. Stored as `{ value }`, the shape a persisted schema form writes.
*/
export function procedureArgumentsKey(address: Address, name: string): KeyInput {
  return ['state', 'procedure', 'schema-form', address, 'procedures', name]
}

/** The arguments last entered for a procedure, or undefined when there are none. */
export function rememberedArguments(address: Address, name: string): unknown {
  const stored = readStored(procedureArgumentsKey(address, name))
  return stored != null && typeof stored === 'object' && 'value' in stored
    ? stored.value
    : undefined
}

export function rememberArguments(address: Address, name: string, value: unknown) {
  writeStored(procedureArgumentsKey(address, name), { value })
}
