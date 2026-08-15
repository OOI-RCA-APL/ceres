import { LevelModel } from '@/api/shared'

/** The record kinds whose views carry a filter bar. */
export type RecordKind = 'messages' | 'particles' | 'alerts' | 'logs'

/** How a condition's value is entered and validated. */
export type FilterValueInput =
  | { type: 'text' }
  | { type: 'date-time' }
  | { type: 'duration' }
  | { type: 'integer'; minimum?: number; exclusiveMaximum?: number }
  | { type: 'enum'; options: readonly string[] }
  | { type: 'address' }

export type FilterDefinition = {
  /** The registry key a stored condition names, also the filter structure field it writes. */
  kind: string
  label: string
  /** Search terms the bar's autocompletion matches, the label included implicitly. */
  aliases: readonly string[]
  input: FilterValueInput
  /** The record kinds whose bars offer this condition. */
  kinds: readonly RecordKind[]
  /** The column whose header quick filter offers it, per record kind it applies to. */
  columns?: Partial<Record<RecordKind, string>>
}

const allKinds = ['messages', 'particles', 'alerts', 'logs'] as const

const timestampColumns = {
  messages: 'timestamp',
  particles: 'timestamp',
  alerts: 'timestamp',
  logs: 'timestamp',
} as const

const levels = LevelModel.options

/** Every filter kind the bar knows, in the order autocompletion offers them.

Compilation, autocompletion, node rendering, and header quick filters all read this list, so
a new filter kind is one entry here and no bar code.
*/
export const filterDefinitions: readonly FilterDefinition[] = [
  {
    kind: 'contains',
    label: 'Contains',
    aliases: ['contains', 'includes', 'text', 'search'],
    input: { type: 'text' },
    kinds: ['messages', 'logs'],
    columns: { messages: 'data', logs: 'content' },
  },
  {
    kind: 'prefix',
    label: 'Prefix',
    aliases: ['prefix', 'starts'],
    input: { type: 'text' },
    kinds: ['messages', 'logs'],
    columns: { messages: 'data', logs: 'content' },
  },
  {
    kind: 'suffix',
    label: 'Suffix',
    aliases: ['suffix', 'ends'],
    input: { type: 'text' },
    kinds: ['messages', 'logs'],
    columns: { messages: 'data', logs: 'content' },
  },
  {
    kind: 'data_contains',
    label: 'Data Contains',
    aliases: ['data', 'contains', 'includes', 'search'],
    input: { type: 'text' },
    kinds: ['particles', 'alerts'],
    columns: { particles: 'data', alerts: 'data' },
  },
  {
    kind: 'data_prefix',
    label: 'Data Prefix',
    aliases: ['data', 'prefix', 'starts'],
    input: { type: 'text' },
    kinds: ['particles', 'alerts'],
    columns: { particles: 'data', alerts: 'data' },
  },
  {
    kind: 'data_suffix',
    label: 'Data Suffix',
    aliases: ['data', 'suffix', 'ends'],
    input: { type: 'text' },
    kinds: ['particles', 'alerts'],
    columns: { particles: 'data', alerts: 'data' },
  },
  {
    kind: 'type',
    label: 'Type',
    aliases: ['type', 'is'],
    input: { type: 'text' },
    kinds: ['particles'],
    columns: { particles: 'type' },
  },
  {
    kind: 'type_contains',
    label: 'Type Contains',
    aliases: ['type', 'contains'],
    input: { type: 'text' },
    kinds: ['particles', 'alerts'],
    columns: { particles: 'type', alerts: 'type' },
  },
  {
    kind: 'type_prefix',
    label: 'Type Prefix',
    aliases: ['type', 'prefix'],
    input: { type: 'text' },
    kinds: ['particles', 'alerts'],
    columns: { particles: 'type', alerts: 'type' },
  },
  {
    kind: 'type_suffix',
    label: 'Type Suffix',
    aliases: ['type', 'suffix'],
    input: { type: 'text' },
    kinds: ['particles', 'alerts'],
    columns: { particles: 'type', alerts: 'type' },
  },
  {
    kind: 'address',
    label: 'Address',
    aliases: ['address', 'component', 'at'],
    input: { type: 'address' },
    kinds: allKinds,
    columns: { messages: 'address', particles: 'address', alerts: 'address', logs: 'address' },
  },
  {
    kind: 'connection',
    label: 'Connection',
    aliases: ['connection', 'port', 'via'],
    input: { type: 'text' },
    kinds: ['messages'],
    columns: { messages: 'connection' },
  },
  {
    kind: 'direction',
    label: 'Direction',
    aliases: ['direction', 'send', 'receive'],
    input: { type: 'enum', options: ['send', 'receive'] },
    kinds: ['messages'],
    columns: { messages: 'direction' },
  },
  {
    kind: 'level',
    label: 'Level',
    aliases: ['level', 'severity'],
    input: { type: 'enum', options: levels },
    kinds: ['alerts', 'logs'],
    columns: { alerts: 'level', logs: 'level' },
  },
  {
    kind: 'min_level',
    label: 'Min Level',
    aliases: ['min', 'level', 'least'],
    input: { type: 'enum', options: levels },
    kinds: ['alerts', 'logs'],
    columns: { alerts: 'level', logs: 'level' },
  },
  {
    kind: 'max_level',
    label: 'Max Level',
    aliases: ['max', 'level', 'most'],
    input: { type: 'enum', options: levels },
    kinds: ['alerts', 'logs'],
    columns: { alerts: 'level', logs: 'level' },
  },
  {
    kind: 'after',
    label: 'After',
    aliases: ['after', 'since', 'from'],
    input: { type: 'date-time' },
    kinds: allKinds,
    columns: timestampColumns,
  },
  {
    kind: 'before',
    label: 'Before',
    aliases: ['before', 'until', 'to'],
    input: { type: 'date-time' },
    kinds: allKinds,
    columns: timestampColumns,
  },
  {
    kind: 'timespan',
    label: 'Timespan',
    aliases: ['timespan', 'last', 'window', 'past'],
    input: { type: 'duration' },
    kinds: allKinds,
    columns: timestampColumns,
  },
  {
    kind: 'after_hour',
    label: 'After Hour',
    aliases: ['hour', 'after'],
    input: { type: 'integer', minimum: 0, exclusiveMaximum: 24 },
    kinds: allKinds,
    columns: timestampColumns,
  },
  {
    kind: 'before_hour',
    label: 'Before Hour',
    aliases: ['hour', 'before'],
    input: { type: 'integer', minimum: 0, exclusiveMaximum: 24 },
    kinds: allKinds,
    columns: timestampColumns,
  },
  {
    kind: 'after_minute',
    label: 'After Minute',
    aliases: ['minute', 'after'],
    input: { type: 'integer', minimum: 0, exclusiveMaximum: 60 },
    kinds: allKinds,
    columns: timestampColumns,
  },
  {
    kind: 'before_minute',
    label: 'Before Minute',
    aliases: ['minute', 'before'],
    input: { type: 'integer', minimum: 0, exclusiveMaximum: 60 },
    kinds: allKinds,
    columns: timestampColumns,
  },
]

const definitionsByKind = new Map(
  filterDefinitions.map((definition) => [definition.kind, definition]),
)

/** The definition a stored condition names, or null for one this console no longer knows. */
export function getFilterDefinition(kind: string): FilterDefinition | null {
  return definitionsByKind.get(kind) ?? null
}

/** The definitions a record kind's bar offers, in autocompletion order. */
export function definitionsFor(recordKind: RecordKind): FilterDefinition[] {
  return filterDefinitions.filter((definition) => definition.kinds.includes(recordKind))
}

/** The definitions a column's header quick filter offers for a record kind. */
export function definitionsForColumn(recordKind: RecordKind, column: string): FilterDefinition[] {
  return definitionsFor(recordKind).filter(
    (definition) => definition.columns?.[recordKind] === column,
  )
}

/** The kind free text falls back to when no definition is picked, the record kind's own
text search. */
export function defaultTextKind(recordKind: RecordKind): string {
  return recordKind === 'messages' || recordKind === 'logs' ? 'contains' : 'data_contains'
}

/** Rank `definitions` against a typed search, prefix matches on the label or an alias first,
then substring matches. An empty search keeps the registry order. */
export function matchDefinitions(
  definitions: FilterDefinition[],
  search: string,
): FilterDefinition[] {
  const normalized = search.trim().toLowerCase()
  if (normalized === '') {
    return definitions
  }

  const terms = (definition: FilterDefinition) => [
    definition.label.toLowerCase(),
    ...definition.aliases,
  ]

  const prefixed = definitions.filter((definition) =>
    terms(definition).some((term) => term.startsWith(normalized)),
  )
  const contained = definitions.filter(
    (definition) =>
      !prefixed.includes(definition) && terms(definition).some((term) => term.includes(normalized)),
  )

  return [...prefixed, ...contained]
}
