import { upperFirst } from 'lodash-es'

import type {
  AccessSource,
  ComponentAccessLevel,
  ComponentEffectiveAccess,
  PermissionTargetType,
} from '@/api/permissions'

// The server reports which input conferred each level, so nothing here has to be inferred. The
// trailing period is appended in `sourceLabel` so group suffixes compose cleanly.
const sourceLabels: Record<AccessSource, string> = {
  admin: 'From administrator status',
  default: 'From default access level',
  component: 'Granted on this component',
  tag: 'Granted through a tag',
  all: 'Granted on all components',
}

/** Label a resolved level, naming the group when a group's grant is what conferred it. */
export function sourceLabel(
  entry: ComponentEffectiveAccess,
  groupNames: Map<string, string>,
): string {
  const label = sourceLabels[entry.source]
  if (entry.origin !== 'group' || entry.group_id == null) {
    return `${label}.`
  }

  const name = groupNames.get(entry.group_id)
  return name == null ? `${label}, through a group.` : `${label}, from group "${name}".`
}

/** Name what a grant applies to, distinguishing a tag from the component of the same name. */
export function permissionTargetLabel(permission: {
  target_type: PermissionTargetType
  target: string
}): string {
  if (permission.target_type === 'all') {
    return 'All components'
  }

  return permission.target_type === 'tag' ? `#${permission.target}` : permission.target
}

export function targetTypeLabel(type: PermissionTargetType): string {
  return type === 'all' ? 'All components' : upperFirst(type)
}

/** What a user may do on one component, after every grant is resolved together. */
export type ResolvedAccess = {
  address: string
  level: ComponentAccessLevel | null
  /** Why the level is what it is, or null where nothing conferred one. */
  source: string | null
  /** The group whose grant conferred the level, which the row links to. */
  groupId: string | null
}

/** Pair every component with the access the server resolved for it, in address order.

Addresses the server reported nothing for are kept, since a component with no access at all is
part of the answer.
*/
export function resolveEffectiveAccess(
  addresses: string[],
  entries: ComponentEffectiveAccess[],
  groupNames: Map<string, string>,
): ResolvedAccess[] {
  const byAddress = new Map(entries.map((entry) => [entry.address, entry]))

  return (
    addresses
      .map((address) => {
        const entry = byAddress.get(address)
        return {
          address,
          level: entry?.level ?? null,
          source: entry == null ? null : sourceLabel(entry, groupNames),
          groupId: (entry?.origin === 'group' ? entry.group_id : null) ?? null,
        }
      })
      // Compared directly rather than with localeCompare, which orders case-insensitively and
      // folds punctuation away. Addresses are machine tokens ordered by code point in the
      // engine, so anything else here would disagree with the order they were returned in.
      .sort((first, second) =>
        first.address < second.address ? -1 : first.address > second.address ? 1 : 0,
      )
  )
}
