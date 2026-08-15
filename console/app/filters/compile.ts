import { definitionsFor } from '@/filters/definitions'
import type { RecordKind } from '@/filters/definitions'
import { createCondition, isBlock } from '@/filters/model'
import type { FilterBlock, FilterItem, FilterQuery } from '@/filters/model'

/** A compiled filter, the flat structure the record APIs accept plus `and`/`or` groups. */
export type CompiledFilter = Record<string, unknown>

/** Whether a condition value counts as set. Blank text is an unfinished condition, not a
filter for the empty string. */
export function hasValue(value: unknown): boolean {
  if (value == null) {
    return false
  }

  if (typeof value === 'string') {
    return value.trim() !== ''
  }

  return true
}

function compiledItems(items: readonly FilterItem[]): CompiledFilter {
  const result: CompiledFilter = {}
  const and: CompiledFilter[] = []

  for (const item of items) {
    if (isBlock(item)) {
      const group = compiledBlock(item)
      if (group != null) {
        and.push(group)
      }

      continue
    }

    if (!hasValue(item.value)) {
      continue
    }

    // A field can only be named once at one level, so a repeat becomes its own and term.
    if (item.kind in result) {
      and.push({ [item.kind]: item.value })
    } else {
      result[item.kind] = item.value
    }
  }

  if (and.length > 0) {
    result.and = and
  }

  return result
}

/** A block as one term of its parent's `and` group, or null when it compiles to nothing.

An `or` block's children are alternatives to each other: the engine ORs a node's own
conditions with each of its `or` children, so the first child stands as the node (through an
`and` group, which the engine hoists into the node's conditions) and the rest as `or` terms.
*/
function compiledBlock(block: FilterBlock): CompiledFilter | null {
  const children = block.children
    .map((child) => (isBlock(child) ? compiledBlock(child) : compiledItems([child])))
    .filter((child): child is CompiledFilter => child != null && Object.keys(child).length > 0)

  if (children.length === 0) {
    return null
  }
  if (children.length === 1) {
    return children[0]!
  }

  if (block.op === 'and') {
    return { and: children }
  }

  return { and: [children[0]!], or: children.slice(1) }
}

/** Compile the bar's query into the filter structure the record APIs accept.

Root items are implicitly `and`ed: conditions merge into the top-level fields and blocks
join as `and` group terms.
*/
export function compileQuery(query: FilterQuery): CompiledFilter {
  return compiledItems(query)
}

/** Seed a query from a widget's stored flat filter, the migration for workspaces saved
before the bar existed. Only fields the record kind's registry knows become conditions. */
export function seedQueryFromFilter(
  filter: Record<string, unknown>,
  recordKind: RecordKind,
): FilterQuery {
  return definitionsFor(recordKind)
    .filter((definition) => hasValue(filter[definition.kind]))
    .map((definition) => createCondition(definition.kind, filter[definition.kind]))
}
