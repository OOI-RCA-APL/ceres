import { v7 } from 'uuid'
import * as z from 'zod'

/** One filter condition, a registry kind carrying its value. */
export type FilterCondition = z.infer<typeof FilterConditionModel>
export const FilterConditionModel = z.object({
  id: z.string().default(() => v7()),
  kind: z.string(),
  value: z.unknown(),
})

/** A logical-operator block holding conditions and nested blocks. */
export type FilterBlock = {
  id: string
  op: 'and' | 'or'
  children: FilterItem[]
}

export type FilterItem = FilterCondition | FilterBlock

export const FilterBlockModel: z.ZodType<FilterBlock> = z.object({
  id: z.string().default(() => v7()),
  op: z.enum(['and', 'or']),
  get children() {
    return z.array(FilterItemModel)
  },
}) as z.ZodType<FilterBlock>

export const FilterItemModel: z.ZodType<FilterItem> = z.union([
  FilterBlockModel,
  FilterConditionModel,
]) as z.ZodType<FilterItem>

/** The bar's whole query, a root list whose items are implicitly `and`ed. */
export type FilterQuery = FilterItem[]
export const FilterQueryModel = z.array(FilterItemModel)

export function isBlock(item: FilterItem): item is FilterBlock {
  return 'op' in item
}

export function createCondition(kind: string, value: unknown = null): FilterCondition {
  return { id: v7(), kind, value }
}

export function createBlock(op: 'and' | 'or', children: FilterItem[] = []): FilterBlock {
  return { id: v7(), op, children }
}

/** Every item in the query in render order, blocks before their children. */
export function flattenQuery(query: FilterQuery): FilterItem[] {
  return query.flatMap((item) => (isBlock(item) ? [item, ...flattenQuery(item.children)] : [item]))
}

/** The item carrying `id`, wherever it nests. */
export function findItem(query: FilterQuery, id: string): FilterItem | null {
  for (const item of flattenQuery(query)) {
    if (item.id === id) {
      return item
    }
  }

  return null
}

/** The query without the items in `ids`, dropping any block emptied by the removal. */
export function withoutItems(query: FilterQuery, ids: ReadonlySet<string>): FilterQuery {
  return query.flatMap((item): FilterItem[] => {
    if (ids.has(item.id)) {
      return []
    }

    if (isBlock(item)) {
      const children = withoutItems(item.children, ids)
      return children.length === 0 ? [] : [{ ...item, children }]
    }

    return [item]
  })
}

/** A deep copy of `items` under fresh IDs, the clipboard's paste form. */
export function withFreshIds(items: FilterItem[]): FilterItem[] {
  return items.map((item) =>
    isBlock(item)
      ? { ...item, id: v7(), children: withFreshIds(item.children) }
      : { ...item, id: v7() },
  )
}

/** Insert `items` at `index` of the root list, clamped to its bounds. */
export function withInserted(query: FilterQuery, items: FilterItem[], index: number): FilterQuery {
  const at = Math.max(0, Math.min(index, query.length))
  return [...query.slice(0, at), ...items, ...query.slice(at)]
}

/** Move the root-level items in `ids` to sit before the root index `index`, keeping their
relative order. Items nested inside blocks stay where they are. */
export function withMoved(
  query: FilterQuery,
  ids: ReadonlySet<string>,
  index: number,
): FilterQuery {
  const moving = query.filter((item) => ids.has(item.id))
  if (moving.length === 0) {
    return query
  }

  const kept = query.filter((item) => !ids.has(item.id))

  // The target index was counted on the full list, so the items before it that are moving
  // no longer occupy slots.
  const movedBefore = query.slice(0, index).filter((item) => ids.has(item.id)).length
  return withInserted(kept, moving, index - movedBefore)
}

/** The root-level items in `ids` grouped into one block of `op` standing where the first of
them stood. Nested items are left in place. */
export function withGrouped(
  query: FilterQuery,
  ids: ReadonlySet<string>,
  op: 'and' | 'or',
): FilterQuery {
  const first = query.findIndex((item) => ids.has(item.id))
  if (first === -1) {
    return query
  }

  const grouped = createBlock(
    op,
    query.filter((item) => ids.has(item.id)),
  )
  const result: FilterQuery = []
  for (const [index, item] of query.entries()) {
    if (index === first) {
      result.push(grouped)
    } else if (!ids.has(item.id)) {
      result.push(item)
    }
  }

  return result
}

/** The query with condition `id` carrying `value`, wherever it nests. */
export function withConditionValue(query: FilterQuery, id: string, value: unknown): FilterQuery {
  return query.map((item): FilterItem => {
    if (isBlock(item)) {
      return { ...item, children: withConditionValue(item.children, id, value) }
    }

    return item.id === id ? { ...item, value } : item
  })
}

/** The query with `item` added to the end of block `id`, wherever it nests. */
export function withAppendedTo(query: FilterQuery, id: string, item: FilterItem): FilterQuery {
  return query.map((current): FilterItem => {
    if (!isBlock(current)) {
      return current
    }

    if (current.id === id) {
      return { ...current, children: [...current.children, item] }
    }

    return { ...current, children: withAppendedTo(current.children, id, item) }
  })
}

/** The query with block `id` joining its children by `op`, wherever it nests. */
export function withBlockOp(query: FilterQuery, id: string, op: 'and' | 'or'): FilterQuery {
  return query.map((item): FilterItem => {
    if (!isBlock(item)) {
      return item
    }

    const children = withBlockOp(item.children, id, op)
    return item.id === id ? { ...item, op, children } : { ...item, children }
  })
}

/** The block `id` dissolved, its children standing where it stood. */
export function withUngrouped(query: FilterQuery, id: string): FilterQuery {
  return query.flatMap((item): FilterItem[] => {
    if (isBlock(item)) {
      if (item.id === id) {
        return item.children
      }

      return [{ ...item, children: withUngrouped(item.children, id) }]
    }

    return [item]
  })
}
